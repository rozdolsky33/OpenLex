# Postmortem: Docker Desktop VM disk exhaustion during Phase 5 statute ingestion

**Date:** 2026-07-14
**Severity:** Low (local dev cluster only, no user-facing impact, no data loss)
**Status:** Resolved

## Summary

While ingesting an expanded statute seed set (18 → 64 sections) into the `kind-openlex`
cluster's Postgres, an insert failed with `DiskFullError: could not extend file... No space
left on device`. The failure aborted its own transaction cleanly (no partial writes), but the
`postgres-0` pod then crash-looped on restart because the node it was scheduled on had zero
free disk. Root cause was **not** Postgres' own storage (its PVC is 1Gi and had headroom) —
it was the shared Docker Desktop VM disk (a single ~134GB virtual disk backing every
container on the host, including all 4 `kind` nodes, other unrelated local projects, and
their volumes) sitting at 100% utilization.

## Timeline (UTC)

- **11:34** — Ran `python -m openlex_worker ingest --source statutes` against the live
  cluster after updating `seed_statutes.json` from 18 to 64 entries. Insert #19 (`RPAPL §
  702`) failed: `asyncpg.exceptions.DiskFullError`. Confirmed the transaction rolled back
  fully — `SELECT count(*) FROM documents` still showed exactly the original 18 statutes + 3
  cases, no partial rows.
- **11:38** — `postgres-0` began `CrashLoopBackOff`. Logs: `FATAL: could not write lock file
  "postmaster.pid": No space left on device`.
- **11:39** — Diagnosed the actual constraint: `docker exec openlex-worker df -h /` showed
  `134G 131G 0 100% /` — the kind node's own overlay filesystem, not the Postgres PVC
  (confirmed separately at 1Gi with room to spare). All kind nodes reported an identical
  reading, confirming they share one underlying virtual disk (Docker Desktop's VM), not
  independent storage.
- **11:39-11:40** — `docker builder prune -f` (safe, no data loss) reclaimed only 166MB —
  insufficient. `docker volume prune -f` (only unattached volumes, confirmed not touching the
  kind cluster or any other running project) reclaimed another 179.8MB — still insufficient.
  Both were the previously-reliable remedy for this exact class of problem earlier in this
  project's history, but this incident had a different, larger root cause.
- **11:40-11:41** — Inspected each kind node's internal containerd image store directly
  (`docker exec <node> crictl images --filter dangling=true`). Found 5-6 large `<none>:<none>`
  dangling images per node — superseded digests of `openlex-api`/`openlex-worker`/`openlex-web`
  left behind by this session's many `kind load docker-image` rebuild cycles, never garbage
  collected by containerd. ~11GB per worker node, ~5.7GB on the control-plane, ~39GB total.
- **11:41** — Removed dangling images on the control-plane node first
  (`crictl images --filter dangling=true -q | xargs crictl rmi`) — succeeded, freeing ~53GB
  system-wide (confirming the shared-disk hypothesis: freeing space via one node's containerd
  GC freed real blocks for every node). Retried the same command on all 3 worker nodes, which
  had originally timed out (containerd's RPC deadline was too tight for GC work while the
  disk was still fully saturated) — succeeded now that there was headroom. All 4 nodes
  converged on `48G` free.
- **11:41** — Force-deleted `postgres-0` to skip the exponential crash-loop backoff window.
  Pod restarted cleanly: normal WAL crash recovery (`redo starts at 0/1CBA358`, one expected
  `invalid record length` entry for the torn in-flight write, then `database system is ready
  to accept connections`). Verified document/case counts were exactly the pre-incident 18 + 3
  before retrying ingestion.
- **11:44** — Re-ran the statute ingestion. Succeeded fully: 64 documents, 64 chunks, 0 errors.

## Root cause

Two compounding factors:

1. **Structural**: `kind load docker-image` (used repeatedly this session to redeploy
   `apps/api`/`apps/worker`/`apps/web` after each code change) pushes a new image layer set
   into every kind node's containerd store on each call, but never removes the digest it
   superseded. Over many rebuild cycles in one long session, this silently accumulates —
   invisible from `docker images` on the host (that only shows the host's own Docker daemon
   image store, a completely separate namespace from each kind node container's internal
   containerd store).
2. **Shared resource**: Docker Desktop's VM disk is one fixed-size virtual disk shared by
   every container the host runs — all 4 kind nodes, this project's `db-test` container, and
   any other local project's Docker/kind usage. Node-level `df -h` numbers are therefore
   identical across nodes and reflect host-wide pressure, not any one workload's actual usage.

## Fix

No code changes — this was an operational/tooling gap, not an application bug. The immediate
fix was manual cleanup (see timeline). No durable automation was added to prevent recurrence
(e.g. a periodic `crictl images --prune` in CI or a pre-flight disk check in
`scripts/kind-load-images.sh`) — flagged below as a real follow-up, not silently dropped.

## What went well

- Postgres' own crash recovery worked exactly as designed — no data loss, no manual WAL
  surgery needed, verified before trusting it (row counts checked pre- and post-recovery, not
  assumed).
- The failing transaction rolled back atomically — no partial/inconsistent statute rows to
  clean up.
- Root cause was found by direct inspection (`df -h` inside containers, `crictl images` per
  node) rather than guessed — the first hypothesis (Postgres' own PVC) was checked and ruled
  out before pursuing the real cause.
- Destructive cleanup actions (`docker volume prune`, `crictl rmi`) were scoped and confirmed
  with the user before running, per this project's standing safety practice — verified
  specifically that no running container's data (kind cluster, other local projects) would be
  touched before proceeding.

## Follow-ups (not yet done)

- `scripts/kind-load-images.sh` could `crictl rmi $(crictl images --filter dangling=true -q)`
  on each node after a successful load, so this doesn't silently re-accumulate across a long
  session.
- No monitoring exists for the *host's* Docker Desktop VM disk (as distinct from in-cluster
  Kubernetes node disk pressure, which `kubelet`/Prometheus's `node_filesystem_*` metrics
  already cover for the node's own view — but that view is misleading here, since the real
  constraint is the shared host-level virtual disk, not any single node's logical capacity).
  Out of scope to build for a local kind dev cluster, but worth naming as a known blind spot.

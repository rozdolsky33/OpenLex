# Phase 6 — CI/CD Hardening — Design

**Status:** approved design, pending implementation plan
**GA checklist:** `docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md`'s Phase 6
(6.1–6.3 covered here; 6.4/6.5 explicitly deferred — see "Explicitly out of scope")
**Builds on:** the existing kind + ArgoCD GitOps setup (`infra/kubernetes/overlays/kind`,
`infra/argocd/apps/kind/`), `scripts/kind-load-images.sh`/`scripts/kind-secrets-bootstrap.sh`'s
established manual-bootstrap conventions, and `evaluation.yml`'s existing docker-compose
stack-bringup pattern.

## Goal

Per `CLAUDE.md`'s scope philosophy, this project's actual purpose is demonstrating SRE/
Platform operational depth, and CI/CD maturity is one of the highest-value remaining gaps:
`tests/integration/` has zero CI coverage (only mock-based tests run today), `tests/end_to_end/`
is a stub README with no real test, and every deployment this whole project has done so far has
been a manual `docker build` + `kind load docker-image` + `kubectl delete pod` sequence run by
hand — there is no actual CI/CD pipeline that builds, publishes, and delivers a real image
without a human doing every step.

This phase makes that real: real tests gated in CI (not manual-only), a real smoke test proving
the golden path actually works end-to-end, and a real build → registry → GitOps delivery
pipeline — while explicitly preserving the fast, free, local-iteration loop that's been used all
along, since that's genuinely still the right tool for iterating on code.

**Explicitly in scope:** gating `tests/integration/` in CI (6.1), replacing the `tests/
end_to_end` stub with a real smoke test (6.2), and a real GHCR-backed, GitOps-delivered deploy
pipeline for the kind cluster with the local-dev fast path preserved (6.3).

**Explicitly out of scope (deferred to a separate Phase 7 spec):** Terraform remote state
(6.4) and Postgres backup/DR (6.5) — both belong with the AWS-flavored follow-on work (RDS
instead of in-cluster Postgres, AWS Secrets Manager + External Secrets Operator), not this
CI/CD-focused pass. Any actual AWS/EKS deployment, ECR, or real cloud spend — this phase stays
entirely GitHub-native (GHCR) and kind-local.

## 6.1 — Gate `tests/integration/` in CI

**Problem:** `api.yml` and `pipelines.yml` only run mock-based unit tests (`apps/api/tests`,
`packages/*/tests`) — nothing in CI ever exercises `legal_retrieval.hybrid_search` or the
ingestion write-path against a real Postgres+pgvector. `tests/integration/` (27+ tests,
including this session's new `test_hybrid_search_caps_one_chunk_per_document` regression test)
only runs when a developer remembers to run `scripts/test-db.sh up` locally.

**Design:** new workflow `.github/workflows/integration.yml`, triggered on PRs touching
`packages/legal_retrieval/**`, `packages/legal_parsing/**`, `packages/legal_models/**`,
`packages/shared/**`, `pipelines/**`, `migrations/**`, `tests/integration/**` (the same set of
paths that can actually break something `tests/integration` would catch). Uses a GitHub
Actions `services:` Postgres container (`pgvector/pgvector:pg16`, matching `scripts/
test-db.sh`'s local image exactly), with a `pg_isready`-based health check gate before the test
step runs. Applies every file in `migrations/postgres/*.sql` in filename order via `psql`
before tests run (mirrors `scripts/test-db.sh reset`'s behavior) — not a hardcoded migration
count, so a future new migration file is picked up automatically. Sets
`TEST_DATABASE_URL` to point at the service container's `localhost` port. Runs `uv run pytest
tests/integration -v`.

No change to `tests/integration/conftest.py` or any test file — this is a CI-wiring change
only, reusing the exact fixtures/connection-string override mechanism that already exists for
local runs.

## 6.2 — Real end-to-end smoke test

**Problem:** `tests/end_to_end/README.md` says "Nothing here yet" and its own stated reason
("no running API to test against") has been stale since `apps/api/src/openlex_api/main.py` was
built — this is now just an empty promise, not a real gap description.

**Design:** replaces the stub with one real smoke test file (`tests/end_to_end/
test_smoke.py`) exercising the actual golden path against a live stack: register/seed a demo
user, `POST /auth/login`, `POST /query` with a question matched to a seeded statute, assert the
response has `abstained: false`, a non-empty answer, at least one citation, and the disclaimer
present. This deliberately does *not* re-test citation accuracy (that's `tests/evaluation`'s
job) — it only proves the full request path (auth → retrieval → generation → response shape)
is alive.

New workflow `.github/workflows/smoke.yml`, triggered on **every PR** (broad trigger — this is
a cheap, fast "is anything fundamentally broken" gate, not a path-filtered specialist check
like `api.yml`/`pipelines.yml`). Reuses `evaluation.yml`'s established stack-bringup pattern
(`docker compose up -d --build db api worker`, wait for `/healthz` to report `status: ok`,
`scripts/ingest.sh statutes`, `scripts/seed-demo-users.sh`) — extracting that bring-up sequence
into a small reusable step isn't required for this phase (duplicating ~15 lines across two
workflows is acceptable; a shared composite action is a fair future refactor if a third
consumer appears, not before). One real Anthropic call (Haiku, matching `evaluation.yml`'s
cost-consciousness precedent), not the full golden-question suite.

## 6.3 — Real deploy pipeline: GHCR + GitOps, local-dev path preserved

**Problem:** there has never been a build that isn't run by a human. Every image this session
has ever deployed was `docker build` + `kind load docker-image` + `kubectl delete pod`, done by
hand, watched, and manually verified. That's the right tool for fast local iteration — but it
means there is no actual CI/CD pipeline, which is a real gap for a project meant to demonstrate
platform engineering maturity.

**Design:**

### Registry and build

New workflow `.github/workflows/deploy.yml`, triggered on push to `main` (i.e., every merge).
Builds `openlex-api`, `openlex-worker`, `openlex-web` (same `Dockerfile`s already in use,
unchanged) and pushes each to GHCR as **private** images:
`ghcr.io/<owner>/openlex-{api,worker,web}:<git-sha>`. Auths via the workflow's own
`GITHUB_TOKEN` with `packages: write` permission — no new secret to provision. Private, not
public: more realistic for a production-like story, and it means the pull path genuinely
exercises registry-auth handling in Kubernetes rather than skipping it.

`deploy.yml` needs an explicit `permissions: {contents: write, packages: write}` block (the
default `GITHUB_TOKEN` scope is read-only on a repo with restrictive default settings, and this
job both pushes packages *and* commits back to `main` — both must be granted explicitly, not
assumed from a passing build).

### GitOps delivery — no network path from GitHub to the local cluster needed

GitHub-hosted runners cannot reach a `kind` cluster running on a laptop — there is no direct
`kubectl apply`/`rollout restart` path from CI to the cluster, and this design does not attempt
one. Instead, `deploy.yml`'s final step runs `kustomize edit set image` inside
`infra/kubernetes/overlays/kind` to point the `images:` transformer at the three freshly-pushed
`ghcr.io/...:<git-sha>` tags, commits that change with a bot identity ("chore: deploy
`<sha>`"), and pushes to `main`. ArgoCD — already running inside the kind cluster and already
watching `main` (`infra/argocd/apps/kind/*.yaml`) — picks up that commit on its own polling
cycle and pulls the new images itself. The pull happens from *inside* the cluster; GitHub never
needs to reach it. This is the standard GitOps pull model, not a workaround.

### Registry auth inside the cluster

New script `scripts/kind-ghcr-pull-secret-bootstrap.sh`, following `scripts/
kind-secrets-bootstrap.sh`'s exact established convention (manual, idempotent, not
ArgoCD-managed — the same accepted local-only exception already used for `openlex-secrets`,
since kind has no IRSA/External Secrets Operator to automate this). Reads a GHCR username +
PAT from `.env` (new `GHCR_USERNAME`/`GHCR_PAT` vars, documented in `.env.example` as
"personal access token with `read:packages` scope, used only to bootstrap the local pull
secret — never wired into `openlex_shared.config.Settings` or any runtime code path," mirroring
`COURTLISTENER_API_TOKEN`'s existing "seed-curation-only, not a runtime setting" framing), and
runs `kubectl create secret docker-registry ghcr-pull-secret --docker-server=ghcr.io
--docker-username=... --docker-password=... --dry-run=client -o yaml | kubectl apply -f -` in
the `openlex` namespace. `infra/kubernetes/base/{api,worker,web}/deployment.yaml` each gain an
`imagePullSecrets: [{name: ghcr-pull-secret}]` entry.

### Local-dev fast path — unchanged, and kept fast

`scripts/kind-load-images.sh` is **not modified** — building and `kind load docker-image`-ing
straight into the cluster's containerd store, with zero registry round-trip, stays exactly as
fast as it is today for iterating on code.

The gap this creates: after `kind-load-images.sh` loads a `:kind-local`-tagged image, the
overlay's committed `images:` block still points at whatever `ghcr.io/...:<sha>` tag the last
real deploy set — so a plain `kubectl apply -k` or ArgoCD sync would keep pulling the old GHCR
image, not the freshly-loaded local one.

New companion script `scripts/use-local-images.sh` closes that gap: runs `kustomize edit set
image openlex-api=openlex-api:kind-local openlex-worker=openlex-worker:kind-local
openlex-web=openlex-web:kind-local` inside `overlays/kind` — an **uncommitted, working-tree-only**
edit. The developer then applies it locally (`kubectl apply -k infra/kubernetes/overlays/kind`,
or lets ArgoCD's local diff show `OutOfSync` and syncs manually) and iterates freely. Because
the edit is never committed, it can't drift from what's actually deployed elsewhere: the next
`git pull` (or the next real `deploy.yml` run) cleanly restores the GHCR-tag state with a plain
`git checkout -- infra/kubernetes/overlays/kind/kustomization.yaml` (or just a fresh clone/pull
overwriting the local edit). Two modes, one overlay, no proliferation, no permanent fork.

### What ArgoCD's own drift-detection sees

Between a real `deploy.yml` run and the next one, `overlays/kind/kustomization.yaml`'s
committed state is the GHCR tags — ArgoCD reports `Synced` against that. While a developer is
using `use-local-images.sh` locally, ArgoCD will report `OutOfSync` (the live cluster state
now differs from the committed manifest) — this is expected and correct, exactly mirroring how
`selfHeal: true` already behaves whenever anyone hand-edits a live resource; it is not a new
failure mode, just the existing one now also covering this specific field.

## Testing

- 6.1: the new workflow itself is the test — verified by opening a PR that touches
  `tests/integration/**` and confirming the Actions log shows the suite actually running (not
  skipped), with a deliberately-broken assertion first to confirm a real failure shows red
  (then reverted), matching this project's "verify every claim live" discipline.
- 6.2: same verification approach — confirm the smoke test runs on an unrelated PR (proving
  the broad trigger works) and fails loudly if the golden path breaks (verified with a
  deliberate temporary breakage, then reverted).
- 6.3: verified by watching one real `deploy.yml` run end-to-end after merging this phase's
  implementation PR — confirm images land in GHCR, confirm the bot commit lands on `main`,
  confirm ArgoCD picks it up and the running pods' `imageID`s match the newly-pushed digests
  (same `kubectl get pods -o custom-columns=...:.status.containerStatuses[0].imageID`
  verification pattern already used throughout this project's prior redeploys).

## Open questions / risks

- **Bot commit noise on `main`:** every merge now produces two commits (the feature merge +
  `deploy.yml`'s tag-bump commit). Acceptable for a single-environment demo project; would need
  a different approach (e.g. a separate `deploy` branch environment) at real multi-environment
  scale — not a concern here.
- **GHCR PAT rotation:** `GHCR_PAT` in `.env` is a personal credential with an expiry;
  `kind-ghcr-pull-secret-bootstrap.sh`'s idempotent re-run is the rotation mechanism (re-run
  after updating `.env`), same pattern as every other credential in this file.
- **Concurrent local-image and GHCR-image use:** if a developer runs `use-local-images.sh`,
  forgets about it, and later triggers something that reads the committed
  `kustomization.yaml` (e.g. checking it into a PR by accident), they'd commit their local
  override. Mitigated by the file being small and the diff being obvious in `git status`/PR
  review, not by tooling — acceptable for a single-developer project.

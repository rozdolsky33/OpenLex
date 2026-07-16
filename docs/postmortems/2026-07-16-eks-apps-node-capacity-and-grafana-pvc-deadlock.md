# Postmortem: EKS apps-node pod-capacity starvation + Grafana PVC/ArgoCD deadlock

**Date:** 2026-07-16
**Severity:** Low (portfolio demo cluster, no real users; app stayed reachable on 2 replicas throughout)
**Status:** Resolved

## Summary

Two independent issues surfaced while stabilizing the EKS demo cluster, both rooted in the
same theme — **a config that looks applied but isn't**:

1. **Apps node group couldn't fit its pods.** The `apps` node group was `t4g.medium`, which caps
   at ~17 pods per node (ENI-IP bound). The platform + app exhausted it, stranding a rescheduled
   `openlex-api` surge pod as `Pending`. The intended fix — VPC-CNI **prefix delegation**
   (`maxPods=110`) — never actually took effect: the `vpc-cni` cluster addon was never created
   (absent from Terraform state, `aws eks describe-addon` returned not-found) across two applies,
   even with `before_compute=true`. Worse, the `maxPods=110` cloudinit override *did* apply, so
   nodes advertised 110 pods against ~17 real IPs and the node-group roll failed outright
   (`NodeCreationFailure: new nodes are not joining`).

2. **Grafana persistence deadlocked ArgoCD.** A gp3 PVC was added so Grafana's SQLite DB would
   survive restarts. But gp3 is `WaitForFirstConsumer`, and ArgoCD **health-gates a PVC to
   `Bound` before it will roll the Deployment that mounts it** — a circular wait: the PVC won't
   bind until a consumer pod exists; the consumer pod won't roll until the PVC binds. The sync
   sat in `phase=Running / waiting for healthy state of .../PersistentVolumeClaim` for ~2.5h,
   the PVC logged 583 `WaitForFirstConsumer` events, and the live Grafana pod quietly stayed on
   `emptyDir` — so the "persistence" was never actually in effect anyway.

## Root causes

### 1. Prefix delegation silently no-op'd; maxPods override silently applied

The two halves of prefix delegation are configured in different places and failed
independently:

- **The CNI setting** (`ENABLE_PREFIX_DELEGATION=true`) lives on the `aws-node` DaemonSet,
  configured via the `vpc-cni` **EKS addon**. Terraform's `cluster_addons = { vpc-cni = {…} }`
  block never resulted in a created addon — the resource wasn't in state and the addon didn't
  exist in the cluster. (Most likely the addon was already present as an EKS *default* addon not
  under Terraform's management, so the managed resource silently did nothing.)
- **The node-side cap** (`maxPods=110`) lives in the node bootstrap (`cloudinit_pre_nodeadm`).
  This *did* apply — so nodes booted advertising 110 pods with no matching IP capacity.

Net: the dangerous half shipped, the enabling half didn't. On `t4g.medium` this bricked the
node roll.

### 2. WaitForFirstConsumer + ArgoCD's PVC health check are mutually exclusive by default

ArgoCD's built-in health assessment for a `PersistentVolumeClaim` is "Healthy ⇔ `Bound`." When
a sync wave contains a WFFC PVC, Argo applies it and then **blocks the operation waiting for it
to go Healthy** before proceeding — but a WFFC PVC by definition only binds once a Pod that
mounts it is scheduled, and that Pod is exactly what the still-pending sisyphean sync hasn't
applied yet. This is a known ArgoCD ↔ WFFC interaction, not a storage or EBS-CSI fault (the
EBS CSI controller/node pods were all healthy).

## Resolution

**Node capacity (PR #72, `develop → main`):**
- Removed the `vpc-cni` `cluster_addons` block and the `maxPods=110` `cloudinit_pre_nodeadm`
  override from `infra/terraform/eks.tf`.
- Bumped the `apps` node group `t4g.medium → t4g.large` (`node_instance_type` default in
  `infra/terraform/variables.tf`).
- After apply + node roll: both `apps` nodes came up `t4g.large`, `Ready`, and — because the
  DaemonSet had *retained* `ENABLE_PREFIX_DELEGATION=true` from an earlier apply and the fresh
  nodes joined *after* it was active — actually reported `max-pods=110` this time. Zero Pending
  pods cluster-wide; `openlex-api` 2/2; `openlex` app `Synced/Healthy`; `/healthz` 200. (The
  irony: prefix delegation works fine — it just needed nodes that boot *after* it's live, which
  is precisely what the earlier same-apply roll never got.)

**Grafana persistence (this change, `develop → main`):**
- Dropped the gp3 PVC entirely; Grafana returns to `emptyDir`. Grafana is **stateless here** —
  every dashboard/datasource is provisioned from ConfigMaps (`observability-dashboards`, always
  `Synced/Healthy`) and users are auto-created by GitHub SSO, so nothing in its SQLite DB needs
  to survive a restart.
- Kept `deploymentStrategy: Recreate` — one Grafana pod at a time, which removes the actual
  motivation for the PVC (the `SQLITE_BUSY`-on-restart 500 only happens when a second pod
  contends for the DB file).
- Deleted the orphan `Pending` PVC.

## What made this take longer than it should have (friction)

This was a slow loop, and most of the delay was *diagnostic latency*, not fix complexity:

- **Silent-partial-apply.** Both root causes were "config that reports success but isn't live."
  Nothing errored loudly — `terraform apply` succeeded, the ArgoCD app just said `Progressing`.
  The truth only showed up in `describe-addon` / the DaemonSet env / the live pod's volume spec.
- **Slow feedback per iteration.** Each node-group instance-type change is a **~10-minute
  destroy+recreate**, and it's driven by hand: I edit → open PR → you review/merge → you
  `checkout main && pull` → `terraform apply` → roll nodes → I verify. A wrong guess costs the
  better part of an hour.
- **Shared working copy / branch drift.** We operate the same checkout. After each merge you'd
  (correctly) `git checkout main && git pull` to apply from `main`, which left *my* session on
  `main`. I repeatedly started editing without re-checking the branch — caught each time by
  `git branch --show-current` + a stash-move to `develop`, but it was avoidable churn.
- **No cheap "is it actually applied?" probe.** Verifying prefix delegation meant remembering to
  check three disconnected places (addon existence, DaemonSet env, node `max-pods`); verifying
  Grafana persistence meant inspecting the live pod's volume, not the Helm values.

## Recommendations (reduce friction next time)

1. **Add a one-shot cluster-truth probe** — a `scripts/eks/verify.sh` that prints the facts that
   silently lie: each node's `instance-type` + `max-pods`, `ENABLE_PREFIX_DELEGATION` on
   `aws-node`, any `Pending` pods, any PVC not `Bound`, and every ArgoCD app's sync/health. One
   command to answer "is what I think I applied actually live?" instead of five ad-hoc `kubectl`
   invocations. (This session ran those queries by hand repeatedly — codify them.)
2. **Prefer instance-type sizing over VPC-CNI prefix delegation for pod capacity** unless
   prefix delegation is *verified* live first. It has two independently-failable halves and the
   dangerous half (maxPods) applies even when the enabling half doesn't. If prefix delegation is
   wanted, gate the `maxPods` bump behind a check that the addon actually exists and the
   DaemonSet env is set — never ship the cap without the capacity.
3. **Never let ArgoCD health-gate a `WaitForFirstConsumer` PVC.** For a workload that genuinely
   needs durable EBS, either (a) use a storageclass with `volumeBindingMode: Immediate` *scoped
   to the workload's AZ* via `allowedTopologies`, or (b) don't manage the PVC as a separately
   health-gated resource. For a stateless workload (Grafana here), just don't add a PVC — the
   provisioning-from-config model already makes it disposable.
4. **Codify the branch-safety habit for the shared checkout.** Because operating from `main`
   after a merge is normal, treat "on `main` with edits" as expected, not exceptional: run
   `git branch --show-current` before every commit and stash-move to `develop` if needed. (Now
   captured in the `git-flow-develop-to-main-only` memory and `CLAUDE.md`.)
5. **Batch slow Terraform changes.** Instance-type changes cost a ~10-min node replacement each;
   bundle capacity/sizing changes into one apply rather than iterating one variable per apply.

## Impact

None user-facing. `openlex-api` served on 2 replicas throughout the node roll; Grafana was
reachable the whole time (it was silently on `emptyDir`, i.e. its real, working state). No data
loss — the only "lost" state was a Grafana SQLite DB that holds nothing durable.

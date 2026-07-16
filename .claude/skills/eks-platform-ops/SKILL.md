---
name: eks-platform-ops
description: Use when operating OpenLex's EKS demo cluster or its interaction with the local kind cluster — kubectl commands unexpectedly hit the wrong cluster, a push to gitops/eks or gitops/kind is rejected as non-fast-forward, a hand-applied ArgoCD-managed patch reverts within ~90s, Grafana/Prometheus show stale or empty data with both compose and kind running, or a pod/PVC sits Pending against EKS node capacity.
---

# EKS Platform & GitOps Ops

Both a local **kind** cluster (`kind-openlex`) and a remote **EKS demo** cluster
(`openlex-eks-demo`) exist at once, both driven by ArgoCD GitOps from machine-managed
branches. Almost every incident in this domain is one of: talking to the wrong cluster,
patching something ArgoCD will silently revert, or force-pushing a deploy branch over history
it didn't have locally. See `local-environment` for bringing environments up/down; this skill
covers cross-environment and EKS-specific operation.

## Rule 1: never trust `kubectl current-context`

kind tooling and port-forward scripts reselect `kind-openlex` as current-context mid-session,
even during EKS work. Symptoms: `the server doesn't have a resource type "servicemonitors"`,
empty pod/resource lookups, or node names like `openlex-control-plane`/`openlex-worker2`
showing up when you expected `ip-10-42-x.ec2.internal` (real EKS node names).

**Pin `--context` on every EKS command, every time** — don't `kubectl config use-context` and
trust it to stick:

```bash
kubectl --context arn:aws:eks:us-east-1:651261648885:cluster/openlex-eks-demo <verb> ...
```

## Rule 2: gitops/* branches are machine-managed — reset before you touch them

ArgoCD tracks `gitops/kind` (from `develop`) and `gitops/eks` (from `main`), **not**
`develop`/`main` directly (see `docs/decisions/0007-argocd-image-updater.md`). Argo CD Image
Updater git-writes new image tags onto these branches continuously, so your local copy goes
stale fast — a stale local branch checked out and pushed will be rejected as non-fast-forward,
and **force-pushing it would revert the live deployment to an old state**.

Delivery pattern for a manifest/overlay change:

1. Land the change on `develop → main` (or `develop` for kind) through the normal PR flow —
   that's the source of truth.
2. `git fetch`, then reset local to the remote tip before touching the deploy branch:
   `git branch -f gitops/eks origin/gitops/eks` (or `gitops/kind`).
3. Cherry-pick the change onto that tip and push (must fast-forward). Confirm first with
   `git rev-list --left-right --count origin/gitops/eks...HEAD` — it must show `behind: 0`.
4. Force an immediate sync instead of waiting for ArgoCD's poll interval:
   `kubectl -n argocd annotate app openlex argocd.argoproj.io/refresh=hard --overwrite`.

Never `git push --force` a `gitops/*` branch. If `git checkout gitops/eks` lands you on a
branch missing recent history (image-updater tag writes, other automated commits), that's the
stale-local-lineage case above — reset, don't force-push over it.

## Rule 3: selfHeal reverts hand-patches — change git, not the live cluster

`selfHeal` is on for ArgoCD-managed apps. A live `kubectl patch`/`kubectl edit` on a
managed resource (Deployment, ServiceMonitor, ConfigMap, etc.) gets reverted within ~90s on
the next reconcile — so it can't be used to verify a fix, even transiently. Any real change
must land in git (see Rule 2) and sync through ArgoCD. Exception: deleting a crash-looping pod
to force a recreate (the Deployment spec itself is unchanged) is safe.

## Rule 4: don't run compose and kind at the same time

Both stacks bind the same localhost ports (Grafana `:3000`, Prometheus `:9090`, Jaeger
`:16686`, API `:8000`, Web `:5173`) — compose binds them directly, kind exposes them via
`kubectl port-forward`. With both up, `localhost:PORT` resolution can split across them
(IPv4 vs IPv6), so you write to one environment and read from the other — dashboards look
empty or inconsistent with nothing actually broken.

If you suspect this, diagnose server-side, not via the browser:

```bash
docker exec openlex-prometheus-1 wget -qO- '.../api/v1/query?query=<your_metric>'
kubectl -n openlex exec deploy/openlex-api -- curl -s '<prom-svc>/api/v1/query?query=<your_metric>'
```

Whichever one has the data is where the request actually landed. Fix: run one environment at a
time — killing the kind observability port-forwards is enough to hand the ports back to
compose (non-destructive; compose has no named volume for Prometheus/Grafana, so that
telemetry is ephemeral either way — `pgdata` is what persists).

## Quick reference

| Symptom | Cause | Fix |
|---|---|---|
| EKS `kubectl` command fails with a resource-type or "not found" error that makes no sense | current-context silently reverted to `kind-openlex` | Re-run with `--context arn:aws:eks:...` pinned (Rule 1) |
| `git push` to `gitops/eks`/`gitops/kind` rejected as non-fast-forward | Local branch is stale relative to Image Updater's writes | `git fetch` + `git branch -f gitops/eks origin/gitops/eks`, then cherry-pick (Rule 2) — never force-push |
| A patch you applied with `kubectl edit`/`kubectl patch` disappears within ~90s | ArgoCD `selfHeal` reverted it | Make the change in git on the deploy branch instead (Rule 3) |
| Grafana/Prometheus show no data or inconsistent data, nothing else looks broken | compose + kind both up, port collision | Query each backend server-side to find where traffic landed; run one environment only (Rule 4) |
| Pod stuck `Pending` on EKS, or a PVC never leaves `Pending`/`WaitForFirstConsumer` while its consumer Deployment also never rolls | Node pod-capacity exhaustion (ENI-IP cap) or ArgoCD's PVC health gate deadlocking against a `WaitForFirstConsumer` StorageClass — see `docs/postmortems/2026-07-16-eks-apps-node-capacity-and-grafana-pvc-deadlock.md` | Check `kubectl describe node`/`describe pvc` for the specific cause; both root causes there were "a config that looks applied but isn't" — verify in AWS/Terraform state, don't assume the manifest took effect |
| Terraform apply blocked on `aws_acm_certificate_validation` or similar pending resource | DNS delegation / cert issuance not yet propagated | See `docs/infrastructure/dns-subdomain-delegation.md` and `docs/infrastructure/web-deploy.md` for the unblock sequence |

## Where the rest lives

- Full EKS bootstrap procedure (ArgoCD install, secrets, image updater activation):
  `docs/infrastructure/eks-argocd-bootstrap.md`.
- Branch/promotion model (`develop` = staging/kind, `main` = production/EKS):
  `docs/infrastructure/dev-workflow-and-branching.md` (see also the top-level "Git workflow"
  section in `CLAUDE.md` — `develop → main` only, never a feature branch straight into `main`)
  — note this doc may lag real state (it was written before EKS went live; verify against
  current cluster state before trusting its "not built yet" framing).
- Image Updater / gitops branch design rationale: `docs/decisions/0007-argocd-image-updater.md`.
- kind-side bring-up/troubleshooting (empty corpus, unseeded users, stale port-forwards):
  `local-environment` skill.

## Guardrails

- Terraform applies, `terraform destroy`, force-deleting AWS resources (e.g. a "scheduled for
  deletion" Secrets Manager secret), and any `git push --force` to a `gitops/*` branch are
  irreversible or affect a live deployment — confirm with the user before running them, even
  if a memory or past session did the same thing before.
- When something "looks applied but isn't" (Terraform state vs. actual cluster state,
  manifest vs. live resource), verify directly (`aws eks describe-addon`, `kubectl get
  <resource> -o yaml`, `terraform state list`) rather than trusting the config file.

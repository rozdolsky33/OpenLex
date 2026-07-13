# Kubernetes manifests (Kustomize)

`base/` + `overlays/` (per-environment), as promised when this was a placeholder. ArgoCD is
the only thing that applies these in practice — see `infra/argocd/`; this directory is what
its Applications point at.

```
base/
├── postgres/  StatefulSet + PVC + Service, init SQL via configMapGenerator over every file
│              in migrations/postgres/ (no duplicated schema) — list every migration here
│              explicitly, adding a new one to the `files:` list; an earlier version of this
│              list only had 0001_init.sql, silently skipping every later migration on kind
├── api/       Deployment (readiness=/healthz) + Service + ServiceAccount
├── worker/    Deployment + ServiceAccount
└── web/       scaffolded, NOT referenced by any overlay yet — apps/web has no Dockerfile/
               package.json (see CLAUDE.md "Current state"); wire it in once it exists

overlays/
├── kind/      local dev — no ingress/TLS (use `kubectl port-forward`), images: kind-loaded
│              local tags, low resource requests. Runs on a 3-node kind cluster (see
│              infra/kubernetes/kind/kind-config.yaml) — one node dedicated to the
│              observability stack (Prometheus/Grafana/Alertmanager/OTel Collector, tainted +
│              scheduled there via infra/argocd/apps/kind/*.yaml's nodeSelector/tolerations),
│              two nodes for app workloads (openlex-api/worker/postgres, via this overlay's
│              nodeSelector). openlex-api runs 2 replicas with anti-affinity + a
│              PodDisruptionBudget for kind-scale HA.
└── eks-demo/  the public demo — ECR image tags, Ingress (app.<domain>) + ExternalSecret,
               resource requests sized for a single shared t4g.medium node
```

**After merging a change to `infra/kubernetes/overlays/kind` or `infra/argocd/apps/kind/*.yaml`
into `main`:** if you verified it locally by applying directly (`kubectl kustomize | kubectl
apply` / `helm upgrade --install`) rather than waiting for ArgoCD — because ArgoCD's Helm
multi-source `$values` reference or the `openlex` Application's single source can't see an
unmerged branch — check that `syncPolicy.automated` is still enabled on the affected
Application(s). As of the observability tracing/HA follow-up, the paused set is
`root-kind`, `openlex`, `kube-prometheus-stack`, and `otel-collector` (confirm with
`kubectl get application -n argocd -o custom-columns=NAME:.metadata.name,AUTOMATED:.spec.syncPolicy.automated`
— any showing `<none>` needs re-enabling)
(`kubectl get application <name> -n argocd -o jsonpath='{.spec.syncPolicy}'`;
re-enable with `kubectl patch application <name> -n argocd --type merge -p
'{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true},"syncOptions":["CreateNamespace=true"]}}}'`
if it was paused for local verification during development) and force a refresh
(`kubectl patch application <name> -n argocd --type merge -p
'{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'`) to confirm it converges
to `Synced`/`Healthy` against the newly-merged `main`, rather than assuming a stale
`OutOfSync` state will resolve itself.

`base/{api,worker}` never define the `openlex-secrets` Secret object, only reference it via
`envFrom.secretRef` — each overlay decides how that Secret gets populated (a manually-bootstrapped
plain Secret in `kind`, an `ExternalSecret`/AWS Secrets Manager in `eks-demo`). See
`docs/infrastructure/mlops-guide.md` for the full walkthrough and `docs/infrastructure/
architecture-diagrams.md` for the topology.

**Kustomize's load restrictor**: `base/postgres` reads `migrations/postgres/0001_init.sql`
from outside its own directory tree, which Kustomize blocks by default. ArgoCD is configured
for this repo-wide (`kustomize.buildOptions` in `infra/argocd/install/argocd-values-*.yaml`).
For manual/local validation:

```bash
kubectl kustomize --load-restrictor=LoadRestrictionsNone infra/kubernetes/overlays/kind
kubectl kustomize --load-restrictor=LoadRestrictionsNone infra/kubernetes/overlays/eks-demo
```

Editing `migrations/postgres/0001_init.sql` produces a new ConfigMap name and rolls the
Postgres StatefulSet — but `docker-entrypoint-initdb.d` only runs against an *empty* data
directory, so this does not re-seed an already-initialized volume (expected Postgres image
behavior, not a bug).

# Kubernetes manifests (Kustomize)

`base/` + `overlays/` (per-environment), as promised when this was a placeholder. ArgoCD is
the only thing that applies these in practice — see `infra/argocd/`; this directory is what
its Applications point at.

```
base/
├── postgres/  StatefulSet + PVC + Service, init SQL via configMapGenerator over
│              migrations/postgres/0001_init.sql (no duplicated schema)
├── api/       Deployment (readiness=/healthz) + Service + ServiceAccount
├── worker/    Deployment + ServiceAccount
└── web/       scaffolded, NOT referenced by any overlay yet — apps/web has no Dockerfile/
               package.json (see CLAUDE.md "Current state"); wire it in once it exists

overlays/
├── kind/      local dev — no ingress/TLS (use `kubectl port-forward`), images: kind-loaded
│              local tags, low resource requests
└── eks-demo/  the public demo — ECR image tags, Ingress (app.<domain>) + ExternalSecret,
               resource requests sized for a single shared t4g.medium node
```

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

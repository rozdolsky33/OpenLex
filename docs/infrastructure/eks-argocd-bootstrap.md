# EKS ArgoCD bootstrap (eks-demo)

How the OpenLex app + platform stack gets deployed to the `openlex-eks-demo` EKS cluster via
GitOps. Unlike the static web app (S3 + CloudFront — see [web-deploy.md](./web-deploy.md)), the
API/worker and the whole observability/platform stack run **in-cluster**, reconciled by ArgoCD
from `infra/argocd/apps/eks-demo/`.

This is a **one-time bootstrap**, and it has prerequisites that are easy to miss. Do them in
order — a half-filled placeholder or an empty ECR repo produces a broken sync, not an error at
bootstrap time.

## Model

`infra/argocd/root-apps/root-eks-demo.yaml` is an **App-of-Apps** root Application. A human
applies it once; ArgoCD then reconciles everything under `infra/argocd/apps/eks-demo/` in
sync-wave order (platform controllers → ingress-nginx → cluster config → the openlex app). The
root tracks branch **`main`**, path `infra/argocd/apps/eks-demo` — so any values you fill in
those manifests **must be committed to `main`** to take effect.

## Prerequisites (in order)

### 1. Cluster reachable

`terraform apply` done (cluster + node groups `Ready`), kubeconfig pointed at it, and your IAM
principal has cluster access:

```bash
aws eks update-kubeconfig --name openlex-eks-demo --region us-east-1
kubectl get nodes   # must succeed — needs the creator access entry (eks.tf) or an access entry
```

### 2. Fill the manifest placeholders (the error-prone step)

The eks-demo manifests ship as templates with `<PLACEHOLDER>` tokens on **config** lines (the
`# Replace <X>` comments are left intact as documentation). **Every** one must be filled, or the
app that owns it fails to sync. Fill config lines only, from Terraform outputs:

| Token | Value (this account) | Source | Appears in |
|---|---|---|---|
| `<DOMAIN>` | `openlex.arwest.dev` | `terraform output domain_name` | `app-external-dns.yaml`, `argocd-ingress.yaml`, `ingress-grafana.yaml`, `overlays/eks-demo/ingress-api.yaml` |
| `<EXTERNAL_DNS_ROLE_ARN>` | `…:role/openlex-eks-demo-external-dns` | `terraform output external_dns_role_arn` | `app-external-dns.yaml` |
| `<EXTERNAL_SECRETS_ROLE_ARN>` | `…:role/openlex-eks-demo-external-secrets` | `terraform output external_secrets_role_arn` | `app-external-secrets.yaml` |
| `<GITHUB_USERNAME>` | `rozdolsky33` | your GitHub login | `app-oauth2-proxy.yaml` |
| `<ACME_EMAIL>` | your email | you | `clusterissuer-letsencrypt.yaml` |
| `<ECR_ACCOUNT>` / `<REGION>` | `651261648885` / `us-east-1` | `terraform output ecr_repository_urls` | `overlays/eks-demo/kustomization.yaml` |

> These are error-prone precisely because they're scattered and some files have the token on
> *two* lines (e.g. an ingress `tls.hosts` **and** `rules.host`). Verify none remain on config
> lines before bootstrapping:
> ```bash
> grep -rnE '<[A-Z_]+>' infra/argocd/apps/eks-demo infra/kubernetes/overlays/eks-demo \
>   | grep -vE ':\s*#'   # expect no output (comment lines with <X> are fine)
> ```

### 3. Images must be in ECR ⚠️ known gap

`overlays/eks-demo/kustomization.yaml` rewrites the api/worker images to
`<ECR_ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/openlex-{api,worker}`, and EKS nodes pull from ECR
via their node-role's `AmazonEC2ContainerRegistryReadOnly` policy. **But `deploy.yml` currently
pushes images to GHCR (`ghcr.io`), not ECR**, and the ECR repos (created by `ecr.tf`) are empty.
Until this is reconciled, the openlex app will `ImagePullBackOff`. Options: add an ECR
build/push (or a GHCR→ECR mirror) to CI, or push once by hand. Track this before expecting the
openlex app to come up. (The platform Helm charts pull from their own public registries and are
unaffected.)

### 4. Secrets

App config comes from AWS Secrets Manager (`openlex/app`) via External Secrets Operator + IRSA —
no manual k8s Secret. Ensure the `openlex/app` secret exists (Terraform's `rds.tf` creates it)
and carries the keys `externalsecret-openlex.yaml` expects.

## Bootstrap

The script is parameterized (despite living under `scripts/kind/`):

```bash
scripts/kind/argocd-bootstrap.sh eks-demo
```

It installs ArgoCD via Helm (`infra/argocd/install/argocd-values-eks-demo.yaml`) and applies
`projects/appproject-eks-demo.yaml` + `root-apps/root-eks-demo.yaml`. ArgoCD takes over from
there. Watch it:

```bash
kubectl -n argocd get applications
```

## Access

ArgoCD, Grafana, and the app are exposed via ingress-nginx + the `*.openlex.arwest.dev` hosts
once cert-manager issues certs and external-dns creates the records. Before DNS/certs settle you
can port-forward — see `scripts/eks/observability-port-forward.sh`.

## Steady state (ongoing deploys)

After bootstrap, you don't re-run anything by hand:

1. Push to `develop` → `deploy.yml` builds + pushes images (see the ECR gap above).
2. Argo CD Image Updater bumps the tracked gitops branch.
3. ArgoCD auto-syncs the new image.

See [dev-workflow-and-branching.md](./dev-workflow-and-branching.md) for the full flow.

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
| `<IMAGE_UPDATER_ROLE_ARN>` | `…:role/openlex-eks-demo-image-updater` | `terraform output image_updater_role_arn` | `app-argocd-image-updater.yaml` |

> These are error-prone precisely because they're scattered and some files have the token on
> *two* lines (e.g. an ingress `tls.hosts` **and** `rules.host`). Verify none remain on config
> lines before bootstrapping:
> ```bash
> grep -rnE '<[A-Z_]+>' infra/argocd/apps/eks-demo infra/kubernetes/overlays/eks-demo \
>   | grep -vE ':\s*#'   # expect no output (comment lines with <X> are fine)
> ```

### 3. Images in ECR

`overlays/eks-demo/kustomization.yaml` rewrites the api/worker images to
`<ECR_ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/openlex-{api,worker}`, and EKS nodes pull from ECR
via their node-role's `AmazonEC2ContainerRegistryReadOnly` policy (no in-cluster pull secret).

`deploy.yml` pushes each image to **both** registries in one build: GHCR (kind pulls from there)
and ECR (eks-demo). It authenticates to ECR with GitHub OIDC — no static keys — assuming the
`github_actions_ecr_push` role (`iam_oidc_github_actions_ecr.tf`, scoped to `develop`). Two
things must be in place for the ECR push to work:

- `terraform apply` has created the `github_actions_ecr_push` role, and
- the `OPENLEX_ECR_PUSH_ROLE_ARN` Actions variable is set — `scripts/eks/github-deploy-vars.sh`
  sets it from `terraform output github_actions_ecr_push_role_arn`.

The first push happens on the next `deploy.yml` run (push to `develop`). To seed ECR immediately
from existing GHCR images without a new build, mirror the multi-arch manifest:

```bash
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin 651261648885.dkr.ecr.us-east-1.amazonaws.com
for i in openlex-api openlex-worker openlex-web; do
  docker buildx imagetools create \
    -t 651261648885.dkr.ecr.us-east-1.amazonaws.com/$i:<SHA> ghcr.io/rozdolsky33/$i:<SHA>
done
```

(`buildx imagetools create` copies the amd64+arm64 manifest list; a plain `docker pull/tag/push`
would flatten it to one arch.) The platform Helm charts pull from their own public registries and
are unaffected.

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

## First-run fixes baked into this repo

The very first real bootstrap of this stack surfaced a cascade of ordering/resource bugs. All are
now fixed in code — documented here so the behavior is understood, not re-discovered:

- **CRD dry-run deadlock.** ArgoCD server-dry-runs every resource up front; the `ClusterIssuer`
  / `ClusterSecretStore` / `ExternalSecret` failed because their CRDs (installed by the wave `-2`
  cert-manager / external-secrets apps) don't exist yet, failing the whole root sync atomically.
  → those resources carry `argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true`.
- **repo-server & application-controller OOM.** At 256Mi they OOMKill while rendering/reconciling
  ~14 Helm charts at once (repo-server OOM shows up as `connection refused → ComparisonError` on
  every app). → both raised to 256Mi req / 768Mi limit in `argocd-values-eks-demo.yaml`. (If you
  bump these on a *running* controller, its StatefulSet pod may be stuck CrashLooping at the old
  limit — `kubectl -n argocd delete pod argocd-application-controller-0` to recreate it.)
- **`openlex-secrets` wave deadlock.** The `ExternalSecret` that creates `openlex-secrets` used to
  live in the openlex app (wave 1), but wave-0 `postgres-exporter` needs that Secret — and ArgoCD
  won't reach wave 1 until wave 0 is healthy. → moved to `externalsecret-openlex-secrets.yaml`
  (root-managed, wave 0), decoupled from the openlex app.

> **postgres-exporter is not a database.** It's a Prometheus exporter that scrapes **RDS** (via
> `openlex-secrets/POSTGRES_EXPORTER_DSN`). eks-demo has no in-cluster Postgres — keep it.

**Iterating on bootstrap fixes:** `root-eks-demo` tracks `main`, so fixes only take effect once
merged. To test a fix branch on a live cluster without a merge, temporarily
`kubectl -n argocd patch application root-eks-demo --type merge -p '{"spec":{"source":{"targetRevision":"<branch>"}}}'`,
then patch it back to `main` (or `kubectl apply -f infra/argocd/root-apps/root-eks-demo.yaml`)
once merged.

## Access

ArgoCD, Grafana, and the app are exposed via ingress-nginx + the `*.openlex.arwest.dev` hosts
once cert-manager issues certs and external-dns creates the records. Before DNS/certs settle you
can port-forward — see `scripts/eks/observability-port-forward.sh`.

- **ArgoCD UI:** https://argocd.openlex.arwest.dev — username `admin` (password below).

### TLS certificates: promote staging → prod

The ingress manifests ship with `cert-manager.io/cluster-issuer: letsencrypt-staging`
(`argocd-ingress.yaml`, `ingress-grafana.yaml`, `overlays/eks-demo/ingress-api.yaml`) —
**staging first, deliberately**, so HTTP-01 reachability can be debugged without burning Let's
Encrypt's production rate limit (5 certs/domain/week). Staging certs are signed by an **untrusted
root** (`CN=(STAGING) …`), so browsers reject them with `NET::ERR_CERT_AUTHORITY_INVALID` — the
site looks like "it won't do HTTPS" even though the TLS handshake and the HTTP→HTTPS `308`
redirect are both working.

Once staging issuance succeeds end-to-end (`kubectl get certificate -A` → `READY=True`), promote
to production by switching each annotation to `letsencrypt-prod` **on the branch that ships it**:

| Ingress | ArgoCD app | Commit to branch |
|---|---|---|
| `argocd-ingress.yaml`, `ingress-grafana.yaml` | `root-eks-demo` | **`main`** |
| `overlays/eks-demo/ingress-api.yaml` | `openlex` | **`gitops/eks`** |

cert-manager sees the changed `issuerRef` and re-issues automatically (no secret deletion needed).
Confirm the served cert is a real Let's Encrypt intermediate, not `(STAGING)`:

```bash
echo | openssl s_client -connect argocd.openlex.arwest.dev:443 \
  -servername argocd.openlex.arwest.dev 2>/dev/null | openssl x509 -noout -issuer
```

> **Gotcha — cert-manager's in-cluster DNS self-check.** Before asking Let's Encrypt to validate,
> cert-manager resolves the challenge host *from inside the cluster* (via CoreDNS) and GETs the
> token path. Right after subdomain delegation / record creation, CoreDNS can still hold a
> negative (NXDOMAIN) cache entry, so the challenge sits `pending` with `... no such host` even
> though the record already resolves **publicly**. It self-heals when the negative cache expires;
> `kubectl -n kube-system rollout restart deployment coredns` clears it immediately.

### Admin login & password reset

The admin password is **not** the default `argocd-initial-admin-secret`. `admin.password` in the
`argocd-secret` is a bcrypt hash driven by External Secrets from **AWS Secrets Manager
`openlex/argocd-admin`** (`argocd-admin-externalsecret.yaml`), which stores `password` (the bcrypt
**hash**, not plaintext) and `passwordMtime`. The plaintext is only whatever you hashed when you
seeded that secret by hand — bcrypt is one-way, so a lost password can't be recovered, only reset.

**Reset through Secrets Manager, not `kubectl patch`.** ESO re-applies `argocd-secret` from
Secrets Manager (`creationPolicy: Merge`, hourly), so a direct patch is reverted on the next sync.

1. bcrypt-hash the new password (cost 10) and build the SM payload. Feed the password via
   **stdin**, never as a shell argument, so `$` / backticks / etc. aren't expanded:

   ```bash
   read -rs PW; echo                       # type it (hidden); not echoed
   uv run --with bcrypt python3 -c 'import sys,bcrypt,json,datetime
   pw=sys.stdin.buffer.read().rstrip(b"\n")
   h=bcrypt.hashpw(pw,bcrypt.gensalt(rounds=10)).decode()
   mt=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
   json.dump({"password":h,"passwordMtime":mt},open("argocd-admin.json","w"))' <<<"$PW"
   unset PW
   ```

2. Write it to Secrets Manager via `file://` (so the `$`-laden hash isn't shell-expanded).
   `passwordMtime` (RFC3339/UTC) is what ArgoCD uses to invalidate existing sessions:

   ```bash
   aws secretsmanager put-secret-value --secret-id openlex/argocd-admin \
     --region us-east-1 --secret-string file://argocd-admin.json
   rm -f argocd-admin.json                 # the file holds the hash — delete it
   ```

3. Force ESO to re-sync, then restart the server so it reloads the credential:

   ```bash
   kubectl -n argocd annotate externalsecret argocd-admin-password force-sync="$(date +%s)" --overwrite
   kubectl -n argocd rollout restart deploy/argocd-server
   ```

4. Log in as `admin` with the new password. Verify without a browser (200 + a `token` = success):

   ```bash
   printf '{"username":"admin","password":"%s"}' "$PW" > login.json  # or hand-write it
   curl -sS -X POST https://argocd.openlex.arwest.dev/api/v1/session \
     -H 'Content-Type: application/json' --data @login.json
   rm -f login.json
   ```

## Image promotion — Argo CD Image Updater (ECR)

The eks openlex app doesn't track `main` directly — it tracks a machine-managed **`gitops/eks`**
branch (the ECR analogue of kind's `gitops/kind`; see ADR-0007). Argo CD Image Updater watches
ECR, picks the newest-built `openlex-{api,worker}` sha image, and git-writes the kustomize image
tags onto `gitops/eks` (based on `main`), which the openlex app then syncs. `main` stays code-only.

- **ECR auth is IRSA, not a pull secret.** The updater's ServiceAccount assumes the
  `image_updater` role (`iam_irsa_image_updater.tf`) and its `ecr-login.sh` script calls
  `aws ecr get-authorization-token` (the updater image ships the aws CLI). Config lives in
  `app-argocd-image-updater.yaml`; the per-app image-list / strategy / git-branch annotations
  live on `app-openlex.yaml`; `imageupdater-openlex.yaml` is the CR that activates it.

**One-time activation (prerequisites):**

1. `terraform apply` — creates the `image_updater` IRSA role; fill `<IMAGE_UPDATER_ROLE_ARN>` in
   `app-argocd-image-updater.yaml` (`terraform output image_updater_role_arn`).
2. Create the AWS Secrets Manager secret **`openlex/image-updater-git`** with keys `username`
   (a GitHub user with push access) and `password` (a `repo`-scoped PAT) — ESO turns it into the
   `argocd-image-updater-git` Secret (`externalsecret-image-updater-git.yaml`).
3. Initialize the branch: `scripts/kind/gitops-branch-init.sh eks-demo` (creates `gitops/eks`
   from `main`).

After that it's hands-off:

1. Push to `develop` → `deploy.yml` builds + pushes `openlex-{api,worker,web}:<sha>` to GHCR **and
   ECR** (no git commit).
2. Image Updater picks the newest sha in ECR and git-writes the tags to `gitops/eks`.
3. ArgoCD syncs the openlex app to the new image.

See [dev-workflow-and-branching.md](./dev-workflow-and-branching.md) for the full flow.

# Terraform (EKS demo only)

Provisions the AWS infrastructure the `eks-demo` GitOps environment runs on: VPC, EKS cluster +
OIDC provider, one Spot node group, a Route53 hosted zone, IRSA roles for `external-dns`/
`external-secrets`, and ECR repositories. It deliberately stops there — ArgoCD (via
`infra/argocd/` + `infra/kubernetes/overlays/eks-demo`) owns everything that runs *inside* the
cluster (ArgoCD itself, ingress-nginx, cert-manager, external-dns, external-secrets, the app).
See `docs/infrastructure/{aws-eks-cost-estimate,mlops-guide}.md` for the cost/architecture
reasoning (no NAT Gateway, no GPU nodes, 1 Spot node).

Local `kind` needs none of this — it's local-only, no AWS involved.

## First-time setup

1. Pick the domain (or a subdomain you're happy to delegate), set it in
   `terraform.tfvars` (copy `terraform.tfvars.example`).
2. `terraform init -backend-config=backend.hcl && terraform apply` (see "Remote state" below
   for the one-time backend bootstrap this needs first).
3. `terraform output route53_name_servers` — set these as the NS records for that domain/
   subdomain at your registrar. Kick this off early; propagation can take a while.
4. Hand-copy `terraform output external_dns_role_arn`, `external_secrets_role_arn`, and
   `ecr_repository_urls` into the committed
   `infra/argocd/apps/eks-demo/app-{external-dns,external-secrets}.yaml` ServiceAccount
   annotations and `infra/kubernetes/overlays/eks-demo/kustomization.yaml`'s `images:` block.
   This is the one place a Terraform output has to flow into a Git-committed manifest by hand —
   an accepted GitOps-purity gap (same category as `kind`'s manual secret bootstrap).
5. `terraform apply` already created `openlex/app` with `DATABASE_URL` and
   `POSTGRES_EXPORTER_DSN` keys (see `rds.tf`). Merge in the remaining keys it needs
   (`ANTHROPIC_API_KEY`, `NY_OPEN_LEG_API_KEY`, `JWT_SECRET_KEY`, `DEMO_*`) — Terraform
   deliberately never touches this secret's value again after its first write (see `rds.tf`'s
   `ignore_changes` comment), so this merge is safe to do once and durable:
   ```bash
   aws secretsmanager get-secret-value --secret-id openlex/app --query SecretString --output text > /tmp/openlex-app.json
   # edit /tmp/openlex-app.json: add ANTHROPIC_API_KEY, NY_OPEN_LEG_API_KEY, JWT_SECRET_KEY,
   # DEMO_* alongside the existing DATABASE_URL key
   aws secretsmanager put-secret-value --secret-id openlex/app --secret-string file:///tmp/openlex-app.json
   rm /tmp/openlex-app.json
   ```
   Separately, create `openlex/argocd-admin` by hand (unchanged) — see
   `infra/argocd/apps/eks-demo/argocd-admin-externalsecret.yaml` for the exact shape expected.

   Also create `openlex/oauth2-proxy` (JSON keys `client_id`, `client_secret`, `cookie_secret`)
   after registering a GitHub OAuth App (see
   `infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml`'s header comment for the exact steps).
6. `aws eks update-kubeconfig --name <cluster_name> --region <region>`, then run
   `scripts/kind/argocd-bootstrap.sh eks-demo`.
7. `kubectl patch storageclass gp2 -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}'` —
   EKS ships `gp2` as the cluster's default StorageClass out of the box; this repo's `gp3`
   StorageClass (`infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml`) needs to be the
   *only* default so PVCs without an explicit `storageClassName` bind correctly.

## Static site deploy (`apps/web`, 7.8)

After `terraform apply`, set these as GitHub repository (or `production` environment)
**variables** (not secrets — none of these are sensitive), Settings -> Secrets and variables ->
Actions -> Variables:

- `OPENLEX_DOMAIN` — the same value as `var.domain_name`.
- `OPENLEX_WEB_BUCKET` — `terraform output web_bucket_name`.
- `OPENLEX_CLOUDFRONT_DISTRIBUTION_ID` — `terraform output cloudfront_distribution_id`.
- `GITHUB_ACTIONS_DEPLOY_WEB_ROLE_ARN` — `terraform output github_actions_deploy_web_role_arn`.

`.github/workflows/deploy-static.yml` then deploys automatically on every push to `main` that
touches `apps/web/**`.

## State

`backend.tf` is configured for an S3 backend (not local-by-default) — `terraform init` requires
either `-backend-config` or explicit `-backend=false`. See "Remote state" below for the
one-time bootstrap and migration steps.

## Remote state

`backend.tf` is configured for an S3 backend, but the bucket/key/region/table values are
supplied separately (Terraform backend blocks can't reference variables or `terraform.tfvars`
at all) via `-backend-config`. One-time bootstrap, before the very first `terraform init` on a
fresh AWS account (an S3 bucket + DynamoDB table can't be created by the same Terraform config
that needs them to exist first):

```bash
aws s3api create-bucket --bucket <your-tfstate-bucket> --region us-east-1
aws s3api put-bucket-versioning --bucket <your-tfstate-bucket> --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket <your-tfstate-bucket> --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws dynamodb create-table \
  --table-name <your-tflock-table> \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

Then:

```bash
cp backend.hcl.example backend.hcl
# edit backend.hcl: real bucket/table names
terraform init -backend-config=backend.hcl -migrate-state
```

**Do this before or alongside the first real `terraform apply` of `rds.tf`** — a real
`aws_db_instance` password ends up in Terraform state via `random_password`/
`aws_secretsmanager_secret_version`, which makes that state file itself sensitive; remote state
(S3 with encryption + restricted IAM access) is meaningfully safer than a local state file on a
laptop for that reason, not just a "more than one person touches this" convenience upgrade.

## Teardown

`terraform destroy` when you're done with the demo. This is what actually stops the EKS
control-plane fee — see `docs/infrastructure/aws-eks-cost-estimate.md`.

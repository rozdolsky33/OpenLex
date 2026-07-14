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
2. `terraform init && terraform apply`.
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
6. `aws eks update-kubeconfig --name <cluster_name> --region <region>`, then run
   `scripts/argocd-bootstrap.sh eks-demo`.
7. `kubectl patch storageclass gp2 -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}'` —
   EKS ships `gp2` as the cluster's default StorageClass out of the box; this repo's `gp3`
   StorageClass (`infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml`) needs to be the
   *only* default so PVCs without an explicit `storageClassName` bind correctly.

## State

Local state by default (see `backend.tf`) — reasonable for a demo cluster you tear down and
recreate between sessions (the cheapest way to run EKS, since the control plane bills hourly
regardless of workload). Switch to an S3+DynamoDB backend once that stops being true.

## Teardown

`terraform destroy` when you're done with the demo. This is what actually stops the EKS
control-plane fee — see `docs/infrastructure/aws-eks-cost-estimate.md`.

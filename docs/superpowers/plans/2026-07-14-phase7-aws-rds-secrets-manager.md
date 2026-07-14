# Phase 7 — AWS RDS + Secrets Manager + Node Topology + CDN + Ingress/Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build (not deploy) the complete Terraform + Kubernetes/ArgoCD infrastructure-as-code
for `eks-demo`'s real cloud-production path — RDS Postgres, verified Secrets Manager/External
Secrets Operator wiring, a two-node-group topology mirroring kind's observability/apps
separation, AWS-native observability (X-Ray/CloudWatch/Grafana), S3+CloudFront static hosting
for `apps/web`, ingress + oauth2-proxy auth for Grafana, and Terraform remote state — all
`terraform validate`-clean and ready to deploy, with zero live AWS deployment in this phase.

**Architecture:** Extends the existing (never-deployed) `infra/terraform/` + `infra/argocd/` +
`infra/kubernetes/overlays/eks-demo/` scaffolding in place — no new top-level directories.
Every new Terraform resource follows the file-per-concern convention already established there
(`ecr.tf`, `iam_irsa_external_dns.tf`, etc.); every new ArgoCD Application follows the
sync-wave + IRSA-pinned-ServiceAccount pattern already used by `external-dns`/
`external-secrets`; every new observability component reuses kind's exact
`openlex.dev/workload` taint/label/toleration strings so the two environments stay
structurally comparable even though `eks-demo`'s backends (X-Ray/CloudWatch) differ completely
from kind's self-hosted stack (Tempo/Jaeger/Loki/Prometheus).

**Tech Stack:** Terraform ~>1.5 (AWS provider ~>5.0, plus new `random`/`tls` providers),
`terraform-aws-modules/eks/aws` ~>20.0, ArgoCD Application CRDs (Helm-chart sources), External
Secrets Operator `v1beta1`, Kustomize overlays, GitHub Actions with OIDC federation.

## Global Constraints

- **No live `terraform apply`, no live AWS deployment of any kind this phase** — every task's
  test is `terraform fmt -check` + `terraform init -backend=false` + `terraform validate` (not
  `terraform plan` — this sandbox has no valid AWS credentials, confirmed via
  `aws sts get-caller-identity` returning `InvalidClientTokenId`; `terraform plan` needs real
  AWS API access even to read `data "aws_availability_zones"`, so it is not executable here and
  is explicitly out of scope, consistent with the phase's own "no live deployment" framing —
  document this in every task's report rather than silently skipping it).
- **No static AWS credentials anywhere** — every AWS-authenticating workload uses IRSA
  (in-cluster) or GitHub OIDC federation (CI), matching the existing `external-dns`/
  `external-secrets` precedent. Never add an `aws_iam_access_key` or a GitHub secret holding a
  raw AWS key.
- **No changes to `docker-compose.yml` or the `develop`/kind GitOps pipeline from Phase 6.**
- **No changes to `scripts/kind-secrets-bootstrap.sh` or any file under
  `infra/kubernetes/overlays/kind/`, `infra/argocd/apps/kind/`, or
  `infra/kubernetes/kind/`** — this is 7.3's isolation guarantee (local kind never gains any
  path to real AWS resources). No dedicated task changes these; the final whole-branch review
  explicitly diffs `main...HEAD` against these paths and must show zero changes.
- **`ArgoCD` does not get `oauth2-proxy` in front of it** — it keeps its own existing native
  login (`argocd-admin-externalsecret.yaml`, unchanged). Only Grafana gets the oauth2-proxy
  gate in this phase (see Task 9's note on resolving a spec-text ambiguity about
  Prometheus/Jaeger, which no longer exist as self-hosted `eks-demo` services under 7.6's
  AWS-native design).
- **CloudFront's ACM certificate must use a `us-east-1` provider alias** regardless of
  `var.region`'s value.
- Every new IRSA `ServiceAccount` name is pinned explicitly in the consuming Application's Helm
  values (never left to the chart default), matching `external-secrets`'/`external-dns`'s
  existing pattern, so each new IAM role's trust-policy `sub` condition actually matches.
- Every new ArgoCD `Application` that pulls from a Helm chart repo not already in
  `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos` must add that repo URL, or
  ArgoCD will refuse to sync it (`AppProject` enforcement).

---

## Note on resolving a real spec ambiguity (7.9)

The spec's 7.9 section says "Grafana/Prometheus/Jaeger need real exposure" and "Prometheus and
Jaeger have no built-in authentication." But 7.6 (added earlier in the same design pass, then
apparently not fully cross-checked against 7.9's later addition) deliberately drops self-hosted
Prometheus and Jaeger from `eks-demo` entirely — metrics go to CloudWatch, traces go to X-Ray,
both are AWS Console/IAM-gated, not Kubernetes Services with something to put an Ingress in
front of. There is nothing named "Prometheus" or "Jaeger" running on `eks-demo` for Task 9 to
expose. This plan resolves the inconsistency by scoping 7.9's ingress + oauth2-proxy gate to
**Grafana only** — the one self-hosted UI `eks-demo` actually has per 7.6 — and treats
CloudWatch/X-Ray as accessed directly via the AWS Console (IAM-gated, no Ingress needed, no
gap left unaddressed).

## Note on a minor spec correction (7.6)

7.6 describes CloudWatch and X-Ray as "both officially supported Grafana datasource types, no
plugin gymnastics." CloudWatch is a Grafana **core** built-in datasource (true, no plugin
needed). X-Ray is a real, Grafana-Labs-catalog-listed datasource, but it does require
installing the `grafana-x-ray-datasource` plugin via the chart's `plugins:` values list — not
"zero plugin gymnastics," but also not a hacky workaround. Task 8 does the plugin install
explicitly and notes this correction inline.

---

## File Structure

New/modified files, grouped by task:

- **Task 1:** `infra/terraform/rds.tf` (new), `infra/terraform/variables.tf`,
  `infra/terraform/versions.tf`, `infra/terraform/README.md` (all modified)
- **Task 2:** `infra/kubernetes/overlays/eks-demo/migrate-job/{kustomization.yaml,job.yaml}`
  (new), `infra/kubernetes/overlays/eks-demo/kustomization.yaml` (modified — drops
  `../../base/postgres`)
- **Task 3:** `infra/argocd/apps/eks-demo/README.md` (new)
- **Task 4:** `infra/terraform/eks.tf`, `infra/terraform/variables.tf` (modified),
  `infra/terraform/iam_irsa_ebs_csi.tf` (new)
- **Task 5:** `infra/kubernetes/overlays/eks-demo/{patch-resources.yaml,pdb-openlex-api.yaml}`
  (new), `infra/kubernetes/overlays/eks-demo/kustomization.yaml` (modified)
- **Task 6:** `infra/argocd/apps/eks-demo/app-otel-collector.yaml` (new),
  `infra/terraform/iam_irsa_otel_collector.tf` (new),
  `infra/terraform/outputs.tf`, `infra/terraform/README.md`,
  `infra/argocd/projects/appproject-eks-demo.yaml` (modified)
- **Task 7:** `infra/argocd/apps/eks-demo/app-fluent-bit.yaml` (new),
  `infra/terraform/iam_irsa_fluent_bit.tf` (new), `infra/terraform/outputs.tf`,
  `infra/terraform/README.md`, `infra/argocd/projects/appproject-eks-demo.yaml` (modified)
- **Task 8:** `infra/argocd/apps/eks-demo/app-grafana.yaml` (new),
  `infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml` (new),
  `infra/terraform/iam_irsa_grafana.tf` (new), `infra/terraform/outputs.tf`,
  `infra/terraform/README.md`, `infra/kubernetes/overlays/eks-demo/kustomization.yaml`,
  `infra/argocd/projects/appproject-eks-demo.yaml` (modified)
- **Task 9:** `infra/argocd/apps/eks-demo/{app-oauth2-proxy.yaml,
  externalsecret-oauth2-proxy.yaml,ingress-grafana.yaml}` (new),
  `infra/argocd/projects/appproject-eks-demo.yaml`, `infra/terraform/README.md` (modified)
- **Task 10:** `infra/terraform/static-site.tf` (new),
  `infra/terraform/iam_oidc_github_actions.tf` (new), `infra/terraform/providers.tf`,
  `infra/terraform/versions.tf`, `infra/terraform/variables.tf`, `infra/terraform/outputs.tf`,
  `infra/kubernetes/overlays/eks-demo/ingress-api.yaml` (all modified)
- **Task 11:** `.github/workflows/deploy-static.yml` (new), `infra/terraform/README.md`
  (modified)
- **Task 12:** `infra/terraform/backend.tf`, `infra/terraform/backend.hcl.example` (new),
  `infra/terraform/README.md`, `.gitignore` (modified)

---

### Task 1: RDS Postgres — Terraform (7.1 core + 7.5 backup/DR)

**Files:**
- Create: `infra/terraform/rds.tf`
- Modify: `infra/terraform/variables.tf`, `infra/terraform/versions.tf`,
  `infra/terraform/README.md`

**Interfaces:**
- Consumes: `module.vpc.vpc_id`/`module.vpc.public_subnets` (`infra/terraform/vpc.tf`),
  `module.eks.node_security_group_id` (`infra/terraform/eks.tf`, exists today, unaffected by
  Task 4's node-group split), `var.cluster_name`/`var.secrets_manager_path_prefix`
  (`infra/terraform/variables.tf`, exist today).
- Produces: `aws_db_instance.openlex` (address used by Task 2's migration Job via the secret
  below, not referenced directly by any other `.tf` file), `aws_secretsmanager_secret.app`
  (name `openlex/app` — Task 2/3/6/7/8's `dataFrom.extract`/`ExternalSecret` references already
  depend on this name existing, which it already does implicitly via the AWS side; no other
  `.tf` file references this resource by name).

- [ ] **Step 1: Add the `random` provider**

Edit `infra/terraform/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
```

- [ ] **Step 2: Add new variables**

Edit `infra/terraform/variables.tf`, appending:

```hcl

variable "db_instance_class" {
  description = "RDS instance class -- Graviton, matches this repo's cost-conscious node-type precedent"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GB (gp3)"
  type        = number
  default     = 20
}

variable "db_backup_retention_days" {
  description = "RDS automated backup retention period, in days"
  type        = number
  default     = 7
}

variable "db_name" {
  description = "Database name inside the RDS instance -- matches local dev's docker-compose convention"
  type        = string
  default     = "openlex"
}

variable "db_username" {
  description = "Master username for the RDS instance -- matches local dev's docker-compose convention"
  type        = string
  default     = "openlex"
}
```

- [ ] **Step 3: Write `rds.tf`**

```hcl
# infra/terraform/rds.tf
#
# Managed Postgres for the eks-demo/production path -- the in-cluster Postgres StatefulSet
# (infra/kubernetes/base/postgres/) stays kind-only from here on; eks-demo's kustomization no
# longer includes it (see Task 2's kustomization.yaml change). See docs/superpowers/specs/
# 2026-07-14-phase7-aws-rds-secrets-manager-design.md's 7.1/7.5.

resource "aws_db_subnet_group" "openlex" {
  name       = "${var.cluster_name}-postgres"
  subnet_ids = module.vpc.public_subnets # no private subnets -- see vpc.tf; isolation is the security group below, not subnet placement
}

# Inbound 5432 only from the EKS nodes' own security group -- the actual isolation boundary
# (publicly_accessible = false on the DB instance itself is the other half of this). No egress
# rule: RDS never initiates outbound connections.
resource "aws_security_group" "rds" {
  name        = "${var.cluster_name}-rds"
  description = "Allow Postgres from EKS nodes only"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "Postgres from EKS nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
}

# special = false avoids URL-encoding gymnastics when this password is interpolated directly
# into a postgresql:// connection string below (special characters like @ or / would otherwise
# need percent-encoding).
resource "random_password" "rds" {
  length  = 32
  special = false
}

resource "aws_db_instance" "openlex" {
  identifier     = "${var.cluster_name}-postgres"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.rds.result

  db_subnet_group_name   = aws_db_subnet_group.openlex.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  backup_retention_period = var.db_backup_retention_days
  backup_window           = "06:00-07:00"        # low-traffic UTC hour
  maintenance_window      = "Mon:07:00-Mon:08:00" # right after the backup window, never overlapping

  # This is a demo cluster meant to be torn down between sessions (see infra/terraform/
  # README.md's "Teardown" section) -- deletion_protection stays false so `terraform destroy`
  # keeps working, but final_snapshot_identifier means that teardown isn't a silent data loss:
  # the last state is always recoverable from the named snapshot.
  deletion_protection       = false
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.cluster_name}-postgres-final"

  apply_immediately          = true
  auto_minor_version_upgrade = true
}

resource "aws_secretsmanager_secret" "app" {
  name = "${var.secrets_manager_path_prefix}/app"
}

# Writes only the DATABASE_URL key on the *first* apply -- the other keys this secret needs
# (ANTHROPIC_API_KEY, NY_OPEN_LEG_API_KEY, JWT_SECRET_KEY, DEMO_*) are external credentials
# Terraform has no business generating, and must be merged in by hand afterward (see
# infra/terraform/README.md's updated step 5). lifecycle.ignore_changes on secret_string means
# that manual merge survives every subsequent `terraform apply` -- without it, re-applying this
# resource would silently overwrite the merged secret back down to just DATABASE_URL, deleting
# the other 4 keys. The real tradeoff: after the first apply, Terraform also stops updating
# DATABASE_URL itself on this secret (e.g. if the DB were ever recreated with a new generated
# password) -- acceptable here since recreating aws_db_instance.openlex is itself a rare,
# deliberate, manually-supervised event, not something that happens silently.
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL = "postgresql+asyncpg://${var.db_username}:${random_password.rds.result}@${aws_db_instance.openlex.address}:5432/${var.db_name}"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
```

- [ ] **Step 4: Update `infra/terraform/README.md` step 5**

Replace the existing step 5 bullet:

```
5. Create the AWS Secrets Manager secrets `external-secrets` will read (`openlex/app`,
   `openlex/argocd-admin`) — see `infra/argocd/apps/eks-demo/argocd-admin-externalsecret.yaml`
   for the exact shape expected.
```

with:

```
5. `terraform apply` already created `openlex/app` with a single `DATABASE_URL` key (see
   `rds.tf`). Merge in the remaining keys it needs (`ANTHROPIC_API_KEY`,
   `NY_OPEN_LEG_API_KEY`, `JWT_SECRET_KEY`, `DEMO_*`) — Terraform deliberately never touches
   this secret's value again after its first write (see `rds.tf`'s `ignore_changes` comment),
   so this merge is safe to do once and durable:
   ```bash
   aws secretsmanager get-secret-value --secret-id openlex/app --query SecretString --output text > /tmp/openlex-app.json
   # edit /tmp/openlex-app.json: add ANTHROPIC_API_KEY, NY_OPEN_LEG_API_KEY, JWT_SECRET_KEY,
   # DEMO_* alongside the existing DATABASE_URL key
   aws secretsmanager put-secret-value --secret-id openlex/app --secret-string file:///tmp/openlex-app.json
   rm /tmp/openlex-app.json
   ```
   Separately, create `openlex/argocd-admin` by hand (unchanged) — see
   `infra/argocd/apps/eks-demo/argocd-admin-externalsecret.yaml` for the exact shape expected.
```

- [ ] **Step 5: Validate**

```bash
cd infra/terraform
terraform fmt -check
terraform init -backend=false
terraform validate
```

Expected: `fmt -check` prints nothing (already formatted); `init -backend=false` succeeds
without needing AWS credentials (no backend configured yet — Task 12 is what changes that);
`validate` prints `Success! The configuration is valid.`

- [ ] **Step 6: Commit**

```bash
git add infra/terraform/rds.tf infra/terraform/variables.tf infra/terraform/versions.tf infra/terraform/README.md
git commit -m "Add RDS Postgres + Secrets Manager wiring for eks-demo (7.1, 7.5)"
```

---

### Task 2: RDS migration Job manifest + eks-demo kustomization update (7.1 cont'd)

**Files:**
- Create: `infra/kubernetes/overlays/eks-demo/migrate-job/kustomization.yaml`,
  `infra/kubernetes/overlays/eks-demo/migrate-job/job.yaml`
- Modify: `infra/kubernetes/overlays/eks-demo/kustomization.yaml`

**Interfaces:**
- Consumes: `migrations/postgres/*.sql` (5 files, exist today:
  `0001_init.sql`...`0005_conversation_ownership.sql`), the `openlex-secrets` k8s Secret's
  `DATABASE_URL` key (produced by Task 1's `aws_secretsmanager_secret_version.app` via ESO —
  same Secret name `apps/{api,worker}` already `envFrom`).
- Produces: nothing consumed by a later task — this is a standalone, manually-applied,
  one-time Job, deliberately not part of the ArgoCD-managed tree.

- [ ] **Step 1: Remove the in-cluster Postgres StatefulSet from eks-demo**

Edit `infra/kubernetes/overlays/eks-demo/kustomization.yaml` — RDS is now the eks-demo
database; the in-cluster `base/postgres` StatefulSet is kind-only from here on:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: openlex

# web is intentionally excluded (apps/web has no Dockerfile yet, see infra/kubernetes/README.md).
# postgres is intentionally excluded -- eks-demo uses RDS (infra/terraform/rds.tf), not an
# in-cluster StatefulSet. That stays kind-only (infra/kubernetes/overlays/kind/).
resources:
  - ../../base/api
  - ../../base/worker
  - externalsecret-openlex.yaml
  - ingress-api.yaml

# Replace <ECR_ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com with `terraform output ecr_repository_urls`
# (infra/terraform) after the first apply, and bump the tag on every image push. See
# infra/kubernetes/README.md and docs/infrastructure/mlops-guide.md's CI-follow-up note —
# this is manual for the first cut, automated later (Argo Image Updater or a CI tag-bump step).
images:
  - name: openlex-api
    newName: <ECR_ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/openlex-api
    newTag: v0.1.0
  - name: openlex-worker
    newName: <ECR_ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/openlex-worker
    newTag: v0.1.0

patches:
  - path: patch-resources.yaml
```

(The `patches:` line references `patch-resources.yaml`, which doesn't exist yet — Task 5
creates it. `terraform validate` doesn't touch Kubernetes YAML, and this file's own
`kubectl kustomize` render — Step 3 below — only exercises the `migrate-job/` subdirectory, not
this top-level one, so this dangling reference is inert until Task 5 lands. This ordering
matches the plan's stated task sequence — Task 5 always runs before this file is expected to
fully `kubectl kustomize` clean.)

- [ ] **Step 2: Write the migration Job's kustomization**

```yaml
# infra/kubernetes/overlays/eks-demo/migrate-job/kustomization.yaml
#
# One-time, manually-applied migration Job for RDS (not part of the ArgoCD-managed eks-demo
# kustomization one level up — this directory is applied directly by an operator, once, after
# RDS is provisioned and before openlex-api first starts):
#   kubectl apply -k infra/kubernetes/overlays/eks-demo/migrate-job
# Re-running is safe: every migrations/postgres/*.sql file uses `CREATE TABLE IF NOT EXISTS`/
# `CREATE INDEX IF NOT EXISTS` guards (see migrations/postgres/0001_init.sql), so a repeat
# apply is a no-op, not destructive -- the same idempotency assumption
# .github/workflows/integration.yml's CI migration-apply loop already relies on.
namespace: openlex

resources:
  - job.yaml

configMapGenerator:
  - name: openlex-migrations
    files:
      - ../../../../migrations/postgres/0001_init.sql
      - ../../../../migrations/postgres/0002_users.sql
      - ../../../../migrations/postgres/0003_conversations.sql
      - ../../../../migrations/postgres/0004_user_tiers.sql
      - ../../../../migrations/postgres/0005_conversation_ownership.sql
```

- [ ] **Step 3: Write the Job**

```yaml
# infra/kubernetes/overlays/eks-demo/migrate-job/job.yaml
#
# DATABASE_URL (from the openlex-secrets Secret, populated by External Secrets Operator from
# Task 1's aws_secretsmanager_secret_version.app) uses the `postgresql+asyncpg://` scheme for
# SQLAlchemy's async driver -- plain `psql` doesn't understand the `+asyncpg` suffix, so the
# entrypoint strips it before connecting.
apiVersion: batch/v1
kind: Job
metadata:
  name: openlex-migrate
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: postgres:16
          envFrom:
            - secretRef:
                name: openlex-secrets
          command:
            - /bin/sh
            - -c
            - |
              set -eu
              CONN="$(echo "$DATABASE_URL" | sed 's/postgresql+asyncpg/postgresql/')"
              for f in $(ls /migrations/*.sql | sort); do
                echo "Applying $f"
                psql "$CONN" -v ON_ERROR_STOP=1 -f "$f"
              done
          volumeMounts:
            - name: migrations
              mountPath: /migrations
      volumes:
        - name: migrations
          configMap:
            name: openlex-migrations
```

- [ ] **Step 4: Render both kustomizations to confirm they're well-formed**

```bash
kubectl kustomize infra/kubernetes/overlays/eks-demo/migrate-job
```

Expected: a rendered `ConfigMap` (with keys `0001_init.sql`...`0005_conversation_ownership.sql`
and their real file contents) followed by the rendered `Job`, both `namespace: openlex` — no
error. This is the task's real, local, AWS-free schema/render check.

```bash
kubectl kustomize infra/kubernetes/overlays/eks-demo 2>&1 | tail -5
```

Expected: fails specifically on the missing `patch-resources.yaml` (`Step 1`'s note above) —
confirm the error names exactly that file and nothing else (i.e. removing `../../base/postgres`
didn't break anything else). Record this expected-fail in the task report; Task 5 resolves it.

- [ ] **Step 5: Commit**

```bash
git add infra/kubernetes/overlays/eks-demo/kustomization.yaml infra/kubernetes/overlays/eks-demo/migrate-job/
git commit -m "Add one-time RDS migration Job, drop in-cluster Postgres from eks-demo (7.1)"
```

---

### Task 3: Secrets Manager + External Secrets Operator — verify and document (7.2)

**Files:**
- Create: `infra/argocd/apps/eks-demo/README.md`

**Interfaces:**
- Consumes: `infra/argocd/apps/eks-demo/secretstore-aws.yaml`,
  `infra/kubernetes/overlays/eks-demo/externalsecret-openlex.yaml`,
  `infra/argocd/apps/eks-demo/argocd-admin-externalsecret.yaml`,
  `infra/argocd/apps/eks-demo/app-external-secrets.yaml`,
  `infra/terraform/iam_irsa_external_secrets.tf` (all exist today, unchanged by Tasks 1-2).
- Produces: a written verification record other tasks/readers can point to; no code interface.

This is a review-and-document task, not new infrastructure — per the spec, "no
functional/behavioral changes expected here... unless the review finds a real bug (in which
case, fix it, and note it explicitly)." Do not invent changes to make the task feel more
substantial than it is; a clean bill of health is a legitimate, complete outcome.

- [ ] **Step 1: Fetch the current External Secrets Operator CRD schema**

Use `WebFetch` on `https://external-secrets.io/latest/api/clustersecretstore/` and
`https://external-secrets.io/latest/api/externalsecret/` (the current official CRD reference
docs). Record the exact page version/date fetched.

- [ ] **Step 2: Cross-check `secretstore-aws.yaml` against the fetched schema**

Read `infra/argocd/apps/eks-demo/secretstore-aws.yaml`. Confirm, against the fetched docs:
- `apiVersion: external-secrets.io/v1beta1` and `kind: ClusterSecretStore` are current/correct.
- `spec.provider.aws.service: SecretsManager` is a valid enum value.
- `spec.provider.aws.auth.jwt.serviceAccountRef.{name,namespace}` is the correct field path for
  IRSA-based (JWT) auth, not the AWS-access-key auth shape.

- [ ] **Step 3: Cross-check `externalsecret-openlex.yaml` and confirm the `dataFrom.extract` claim**

Read `infra/kubernetes/overlays/eks-demo/externalsecret-openlex.yaml`. Confirm:
- `apiVersion`/`kind`/`spec.secretStoreRef`/`spec.target.{name,creationPolicy}` match the
  fetched `ExternalSecret` schema.
- `spec.dataFrom[0].extract.key: openlex/app` pulls **every** top-level JSON key from that
  secret dynamically (not a fixed, named list) — per the fetched docs' description of
  `dataFrom.extract`, this means Task 1's new `DATABASE_URL` key (and any keys manually merged
  in per Task 1's updated README step 5) flow into the `openlex-secrets` k8s Secret
  automatically, with **no changes needed to this file**. State this conclusion explicitly in
  the output doc (Step 6) rather than just asserting it.

- [ ] **Step 4: Cross-check `argocd-admin-externalsecret.yaml`**

Read `infra/argocd/apps/eks-demo/argocd-admin-externalsecret.yaml`. Confirm `spec.target.name:
argocd-secret` + `creationPolicy: Merge` is the correct shape for adding keys to an
already-chart-created Secret without clobbering `server.secretkey` and friends, per the fetched
`ExternalSecret` docs' description of `creationPolicy`.

- [ ] **Step 5: Cross-check the IRSA trust policy**

Read `infra/terraform/iam_irsa_external_secrets.tf`. Confirm the `StringEquals` condition's
value `system:serviceaccount:external-secrets:external-secrets` matches
`infra/argocd/apps/eks-demo/app-external-secrets.yaml`'s `serviceAccount.name: external-secrets`
under the `external-secrets` namespace (the Application's `spec.destination.namespace`).

- [ ] **Step 6: Write the verification record**

```markdown
# infra/argocd/apps/eks-demo/README.md

Verification notes for the Secrets Manager + External Secrets Operator chain (`secretstore-aws.yaml`,
`../../kubernetes/overlays/eks-demo/externalsecret-openlex.yaml`,
`argocd-admin-externalsecret.yaml`, `app-external-secrets.yaml`,
`../../terraform/iam_irsa_external_secrets.tf`) — see
`docs/superpowers/specs/2026-07-14-phase7-aws-rds-secrets-manager-design.md`'s 7.2. None of
this has ever run against a real cluster; this is a manual schema/consistency review, not a
live test.

**Checked against:** External Secrets Operator's official CRD reference docs,
`https://external-secrets.io/latest/api/clustersecretstore/` and
`.../api/externalsecret/` (fetched <date>).

**Findings:**
- `ClusterSecretStore`/`ExternalSecret` `apiVersion`/`spec` shapes match the current
  documented `v1beta1` schema — no changes needed.
- `externalsecret-openlex.yaml`'s `dataFrom.extract` pulls every top-level key from
  `openlex/app` dynamically. Task 1 (7.1)'s new `DATABASE_URL` key, and any keys manually
  merged into that secret per `infra/terraform/README.md`'s updated step 5, flow into the
  `openlex-secrets` k8s Secret automatically — **confirmed, not just asserted**, against the
  fetched `extract` field description. No changes needed to this file.
- `argocd-admin-externalsecret.yaml`'s `creationPolicy: Merge` is the correct choice for
  adding keys to the chart-created `argocd-secret` without clobbering existing keys — no
  changes needed.
- IRSA trust policy (`iam_irsa_external_secrets.tf`)'s `sub` condition matches
  `app-external-secrets.yaml`'s pinned `serviceAccount.name`/namespace exactly — no changes
  needed.
- `infra/terraform/README.md`'s step 4 (hand-copying `external_secrets_role_arn` into
  `app-external-secrets.yaml`'s ServiceAccount annotation) is accurate; the
  `<EXTERNAL_SECRETS_ROLE_ARN>` placeholder is unambiguous.

**Outcome:** no functional or behavioral changes to any file in this chain — see git log for
this commit, which touches only this README.
```

If any cross-check in Steps 2-5 actually surfaces a real inconsistency against the fetched
docs, fix the specific file in the same commit and add a `**Bug found and fixed:**` bullet
describing it — do not silently absorb a real finding into the "no changes needed" bullets
above.

- [ ] **Step 7: Commit**

```bash
git add infra/argocd/apps/eks-demo/README.md
git commit -m "Verify and document Secrets Manager / External Secrets Operator wiring (7.2)"
```

---

### Task 4: Node topology — Terraform: two node groups + EBS CSI driver (7.7 core)

**Files:**
- Modify: `infra/terraform/eks.tf`, `infra/terraform/variables.tf`
- Create: `infra/terraform/iam_irsa_ebs_csi.tf`

**Interfaces:**
- Consumes: `module.eks.oidc_provider_arn`/`module.eks.oidc_provider`/`module.eks.cluster_name`
  (produced by the `module "eks"` block itself, standard module outputs).
- Produces: two node-group labels or workloads to schedule against —
  `openlex.dev/workload: observability` (tainted `NoSchedule`) and `openlex.dev/workload:
  apps` (untainted) — Task 5's `patch-resources.yaml` and Tasks 6-9's ArgoCD Applications all
  depend on these exact label/taint strings existing. `aws_eks_addon.ebs_csi` — Task 8's
  Grafana PVC depends on the CSI driver this installs (not referenced by name, just by the
  `ebs.csi.aws.com` provisioner existing in-cluster).

- [ ] **Step 1: Replace the single node group with two, in `eks.tf`**

```hcl
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = false

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets # no private subnets — see vpc.tf

  enable_irsa = true

  node_security_group_additional_rules = local.node_security_group_additional_rules

  eks_managed_node_groups = {
    # Mirrors kind's dedicated-worker split (docs/infrastructure/kubernetes-topology.md):
    # ArgoCD + the observability stack (Grafana/OTel Collector/Fluent Bit — kept minimal per
    # docs/superpowers/specs/2026-07-14-phase7-aws-rds-secrets-manager-design.md's 7.6, but
    # still real workloads with real PVCs) get their own node group, tainted so nothing else
    # schedules there by accident.
    observability = {
      instance_types = [var.observability_node_instance_type] # larger than apps — see variables.tf
      capacity_type  = "SPOT"

      min_size     = 1
      max_size     = 2
      desired_size = 1

      subnet_ids = module.vpc.public_subnets

      labels = {
        "openlex.dev/workload" = "observability"
      }
      taints = {
        observability = {
          key    = "openlex.dev/workload"
          value  = "observability"
          effect = "NO_SCHEDULE"
        }
      }
    }

    # Fixed at 2 (not an ASG range) — one per AZ (vpc.tf provisions 2), so openlex-api's hard
    # anti-affinity (infra/kubernetes/overlays/eks-demo/patch-resources.yaml, Task 5) always
    # has somewhere to schedule both replicas.
    apps = {
      instance_types = [var.node_instance_type] # Graviton/arm64 — no GPU needed
      capacity_type  = "SPOT"

      min_size     = 2
      max_size     = 2
      desired_size = 2

      subnet_ids = module.vpc.public_subnets

      labels = {
        "openlex.dev/workload" = "apps"
      }
      # ECR pull permissions for the node role come from the AmazonEC2ContainerRegistryReadOnly
      # policy the module attaches by default to every managed node group's IAM role.
    }
  }
}
```

- [ ] **Step 2: Update `variables.tf`**

Remove the `node_desired_size` variable (no longer meaningful — both node groups now have
fixed/self-descriptive sizing directly in `eks.tf`). Update `node_instance_type`'s description
and add `observability_node_instance_type`:

```hcl
variable "node_instance_type" {
  description = "Instance type for the `apps` node group — no GPU needed (see ml/model_cards/bge-small-en-v1.5.md)"
  type        = string
  default     = "t4g.medium"
}

variable "observability_node_instance_type" {
  description = "Instance type for the `observability` node group — larger than apps: Grafana + OTel Collector + Fluent Bit + ArgoCD together need more headroom"
  type        = string
  default     = "t4g.large"
}
```

(Delete the old `variable "node_desired_size" { ... }` block entirely.)

- [ ] **Step 3: Write the EBS CSI driver IRSA + addon**

```hcl
# infra/terraform/iam_irsa_ebs_csi.tf
#
# IRSA role for the EKS-managed `aws-ebs-csi-driver` addon's controller ServiceAccount
# (namespace kube-system, name ebs-csi-controller-sa — the addon creates and manages this
# ServiceAccount itself; module.eks (enable_irsa = true) already created the cluster's OIDC
# provider used below). Required for Grafana's PersistentVolumeClaim (Task 8) on the
# observability node group to actually provision a real gp3 EBS volume — without this addon,
# PVCs on eks-demo stay Pending forever (no CSI driver == no dynamic provisioning).
data "aws_iam_policy_document" "ebs_csi_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_csi" {
  name               = "${var.cluster_name}-ebs-csi"
  assume_role_policy = data.aws_iam_policy_document.ebs_csi_trust.json
}

# AWS-managed policy, not a hand-written document -- this is AWS's own recommended pattern for
# the EBS CSI driver specifically (unlike external-dns/external-secrets, which need narrowly
# scoped custom policies this project writes itself).
resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name             = module.eks.cluster_name
  addon_name               = "aws-ebs-csi-driver"
  service_account_role_arn = aws_iam_role.ebs_csi.arn
}
```

- [ ] **Step 4: Validate**

```bash
cd infra/terraform
terraform fmt -check
terraform init -backend=false
terraform validate
```

Expected: `Success! The configuration is valid.` (see Task 1 Step 5's note on why `terraform
plan` isn't run in this environment.)

- [ ] **Step 5: Commit**

```bash
git add infra/terraform/eks.tf infra/terraform/variables.tf infra/terraform/iam_irsa_ebs_csi.tf
git commit -m "Split eks-demo into observability/apps node groups, add EBS CSI driver (7.7)"
```

---

### Task 5: Node topology — eks-demo Kubernetes overlay (7.7 cont'd)

**Files:**
- Create: `infra/kubernetes/overlays/eks-demo/patch-resources.yaml`,
  `infra/kubernetes/overlays/eks-demo/pdb-openlex-api.yaml`
- Modify: `infra/kubernetes/overlays/eks-demo/kustomization.yaml`

**Interfaces:**
- Consumes: the `openlex.dev/workload: apps` label from Task 4's `eks.tf`,
  `topology.kubernetes.io/zone` (a standard EKS-node label, not something this project sets).
- Produces: nothing consumed by a later task.

- [ ] **Step 1: Write `patch-resources.yaml`**

```yaml
# infra/kubernetes/overlays/eks-demo/patch-resources.yaml
#
# Mirrors infra/kubernetes/overlays/kind/patch-resources.yaml's nodeSelector/anti-affinity
# pattern, adjusted for a real multi-AZ cluster (see infra/terraform/eks.tf's `apps` node
# group — fixed at 2 nodes, one per AZ): anti-affinity is `required` (hard), not kind's
# `preferred` (soft), and topologyKey is the AZ label, not the per-node hostname label —
# safe here specifically because EKS managed node groups replace a drained/failed node
# automatically, unlike kind's fixed 2-node ceiling (see docs/infrastructure/
# kubernetes-topology.md for why kind stays soft).
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openlex-api
spec:
  replicas: 2
  template:
    spec:
      nodeSelector:
        openlex.dev/workload: apps
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app.kubernetes.io/name: openlex-api
              topologyKey: topology.kubernetes.io/zone
      containers:
        - name: api
          imagePullPolicy: IfNotPresent
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 60
            periodSeconds: 10
            failureThreshold: 6
          livenessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 90
            periodSeconds: 15
            failureThreshold: 5
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openlex-worker
spec:
  template:
    spec:
      nodeSelector:
        openlex.dev/workload: apps
      containers:
        - name: worker
          imagePullPolicy: IfNotPresent
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
```

(No `postgres` StatefulSet patch — Task 2 already removed `../../base/postgres` from this
overlay's resources.)

- [ ] **Step 2: Write the PDB**

```yaml
# infra/kubernetes/overlays/eks-demo/pdb-openlex-api.yaml
#
# Same as infra/kubernetes/overlays/kind/pdb-openlex-api.yaml — backs the "HA" claim of the
# `apps` node group's 2 fixed replicas/2 AZs (infra/terraform/eks.tf) during voluntary
# disruptions (node drain, EKS-managed-node-group instance replacement).
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: openlex-api
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: openlex-api
```

- [ ] **Step 3: Wire the PDB into the kustomization**

Edit `infra/kubernetes/overlays/eks-demo/kustomization.yaml`'s `resources:` list (from Task
2's version) to add `pdb-openlex-api.yaml`:

```yaml
resources:
  - ../../base/api
  - ../../base/worker
  - externalsecret-openlex.yaml
  - ingress-api.yaml
  - pdb-openlex-api.yaml
```

(`patches: - path: patch-resources.yaml` already exists from Task 2's version of this file —
no change needed there; this step only adds the new `resources:` entry.)

- [ ] **Step 4: Render and confirm the overlay is now fully well-formed**

```bash
kubectl kustomize infra/kubernetes/overlays/eks-demo
```

Expected: succeeds now (Task 2 Step 4 recorded this failing on the missing
`patch-resources.yaml` — confirm that specific error is gone). Manually inspect the rendered
`openlex-api` Deployment: `nodeSelector.openlex.dev/workload: apps`,
`affinity.podAntiAffinity.requiredDuringSchedulingIgnoredDuringExecution[0].topologyKey:
topology.kubernetes.io/zone`, `replicas: 2`. Manually inspect the rendered PDB:
`spec.minAvailable: 1`.

- [ ] **Step 5: Verify the reused taint/label strings are byte-identical to kind's**

```bash
grep -n "openlex.dev/workload" infra/kubernetes/kind/kind-config.yaml infra/kubernetes/overlays/eks-demo/patch-resources.yaml infra/terraform/eks.tf
```

Expected: every match uses exactly `openlex.dev/workload` (key) and `observability`/`apps`
(values) — no typos, no case differences. A typo'd taint value is a silent scheduling failure,
not a `terraform validate`/`kubectl kustomize` error, so this must be checked by eye, not
tooling. Record the exact command output in the task report.

- [ ] **Step 6: Commit**

```bash
git add infra/kubernetes/overlays/eks-demo/patch-resources.yaml infra/kubernetes/overlays/eks-demo/pdb-openlex-api.yaml infra/kubernetes/overlays/eks-demo/kustomization.yaml
git commit -m "Add eks-demo hard anti-affinity + PDB for the apps node group (7.7)"
```

---

### Task 6: Cloud observability — OTel Collector, X-Ray + CloudWatch EMF (7.6a)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-otel-collector.yaml`,
  `infra/terraform/iam_irsa_otel_collector.tf`
- Modify: `infra/terraform/outputs.tf`, `infra/terraform/README.md`,
  `infra/argocd/projects/appproject-eks-demo.yaml`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability` taint/label (Task 4).
- Produces: `aws_iam_role.otel_collector.arn` (output `otel_collector_role_arn`, hand-copied
  into this task's own Application YAML per the existing README-step-4 convention — no other
  task consumes this).

- [ ] **Step 1: Write the OTel Collector IRSA role**

```hcl
# infra/terraform/iam_irsa_otel_collector.tf
#
# IRSA role for the OTel Collector's ServiceAccount (namespace observability, name
# otel-collector — pinned explicitly in app-otel-collector.yaml's serviceAccount.name so this
# trust condition matches exactly, same approach as external-secrets/external-dns).
data "aws_iam_policy_document" "otel_collector_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:observability:otel-collector"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "otel_collector" {
  name               = "${var.cluster_name}-otel-collector"
  assume_role_policy = data.aws_iam_policy_document.otel_collector_trust.json
}

# Minimum permissions for the collector's awsxray + awsemf exporters (AWS's own documented
# requirements for each): X-Ray write for traces, CloudWatch Logs/PutMetricData write for the
# embedded-metric-format metrics pipeline.
data "aws_iam_policy_document" "otel_collector_permissions" {
  statement {
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
      "xray:GetSamplingStatisticSummaries",
    ]
    resources = ["*"] # X-Ray write actions do not support resource-level scoping
  }

  statement {
    effect = "Allow"
    actions = [
      "logs:PutLogEvents",
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "cloudwatch:PutMetricData",
    ]
    resources = ["*"] # matches AWS's own documented awsemf/CloudWatch exporter policy example
  }
}

resource "aws_iam_role_policy" "otel_collector" {
  name   = "otel-collector-xray-cloudwatch"
  role   = aws_iam_role.otel_collector.id
  policy = data.aws_iam_policy_document.otel_collector_permissions.json
}
```

- [ ] **Step 2: Add the output**

Edit `infra/terraform/outputs.tf`, appending:

```hcl

output "otel_collector_role_arn" {
  description = "Paste into infra/argocd/apps/eks-demo/app-otel-collector.yaml's serviceAccount.annotations"
  value       = aws_iam_role.otel_collector.arn
}
```

- [ ] **Step 3: Add the OTel Collector chart repo to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://open-telemetry.github.io/opentelemetry-helm-charts
```

- [ ] **Step 4: Write the Application**

```yaml
# infra/argocd/apps/eks-demo/app-otel-collector.yaml
#
# Same chart/version as infra/argocd/apps/kind/app-otel-collector.yaml, different exporters:
# awsxray (traces -> AWS X-Ray) + awsemf (metrics -> CloudWatch, embedded metric format)
# instead of otlp/tempo + otlp/jaeger — see docs/superpowers/specs/
# 2026-07-14-phase7-aws-rds-secrets-manager-design.md's 7.6. Uses the *-contrib collector
# image, unlike kind's core image, because awsxray/awsemf are contrib-only exporters (not
# shipped in the core otel/opentelemetry-collector image kind's values-base.yaml pins).
# Replace <OTEL_COLLECTOR_ROLE_ARN> with `terraform output otel_collector_role_arn`.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: otel-collector
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  source:
    repoURL: https://open-telemetry.github.io/opentelemetry-helm-charts
    chart: opentelemetry-collector
    targetRevision: "0.165.*"
    helm:
      valuesObject:
        mode: deployment
        image:
          repository: otel/opentelemetry-collector-contrib
        command:
          name: otelcol-contrib
        serviceAccount:
          create: true
          name: otel-collector
          annotations:
            eks.amazonaws.com/role-arn: "<OTEL_COLLECTOR_ROLE_ARN>"
        nodeSelector:
          openlex.dev/workload: observability
        tolerations:
          - key: openlex.dev/workload
            operator: Equal
            value: observability
            effect: NoSchedule
        resources:
          requests: { cpu: 25m, memory: 64Mi }
          limits: { cpu: 200m, memory: 256Mi }
        config:
          receivers:
            otlp:
              protocols:
                grpc:
                  endpoint: 0.0.0.0:4317
                http:
                  endpoint: 0.0.0.0:4318
          processors:
            batch: {}
          exporters:
            awsxray:
              region: us-east-1
            awsemf:
              region: us-east-1
              namespace: OpenLex
              log_group_name: "/openlex/eks-demo/metrics"
          service:
            pipelines:
              traces:
                receivers: [otlp]
                processors: [batch]
                exporters: [awsxray]
              metrics:
                receivers: [otlp]
                processors: [batch]
                exporters: [awsemf]
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 5: Note the new README hand-copy target**

Edit `infra/terraform/README.md` step 4's list to add `otel_collector_role_arn`:

```
4. Hand-copy `terraform output external_dns_role_arn`, `external_secrets_role_arn`,
   `otel_collector_role_arn`, and `ecr_repository_urls` into the committed
   `infra/argocd/apps/eks-demo/app-{external-dns,external-secrets,otel-collector}.yaml`
   ServiceAccount annotations and `infra/kubernetes/overlays/eks-demo/kustomization.yaml`'s
   `images:` block. This is the one place a Terraform output has to flow into a Git-committed
   manifest by hand — an accepted GitOps-purity gap (same category as `kind`'s manual secret
   bootstrap).
```

- [ ] **Step 6: Validate**

```bash
cd infra/terraform && terraform fmt -check && terraform init -backend=false && terraform validate
```

Expected: `Success! The configuration is valid.`

Manually cross-check `app-otel-collector.yaml`'s `config:` block against the OTel Collector
`awsxray`/`awsemf` exporter docs (`WebFetch`
`https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/awsxrayexporter`
and `.../exporter/awsemfexporter`, record what was checked in the task report) — confirm
`region`/`namespace`/`log_group_name` are the documented field names for each exporter.

- [ ] **Step 7: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-otel-collector.yaml infra/terraform/iam_irsa_otel_collector.tf infra/terraform/outputs.tf infra/terraform/README.md infra/argocd/projects/appproject-eks-demo.yaml
git commit -m "Add OTel Collector for eks-demo: X-Ray traces + CloudWatch EMF metrics (7.6)"
```

---

### Task 7: Cloud observability — Fluent Bit, CloudWatch Logs (7.6b)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-fluent-bit.yaml`,
  `infra/terraform/iam_irsa_fluent_bit.tf`
- Modify: `infra/terraform/outputs.tf`, `infra/terraform/README.md`,
  `infra/argocd/projects/appproject-eks-demo.yaml`

**Interfaces:**
- Consumes: nothing from earlier tasks (deliberately unrestricted by the observability
  node-group taint — see Step 3's note).
- Produces: `aws_iam_role.fluent_bit.arn` (output `fluent_bit_role_arn`).

- [ ] **Step 1: Write the Fluent Bit IRSA role**

```hcl
# infra/terraform/iam_irsa_fluent_bit.tf
#
# IRSA role for aws-for-fluent-bit's ServiceAccount (namespace observability, name
# aws-for-fluent-bit — pinned explicitly in app-fluent-bit.yaml's serviceAccount.name).
data "aws_iam_policy_document" "fluent_bit_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:observability:aws-for-fluent-bit"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fluent_bit" {
  name               = "${var.cluster_name}-fluent-bit"
  assume_role_policy = data.aws_iam_policy_document.fluent_bit_trust.json
}

data "aws_iam_policy_document" "fluent_bit_permissions" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = ["arn:aws:logs:${var.region}:*:log-group:/openlex/eks-demo/*"]
  }
}

resource "aws_iam_role_policy" "fluent_bit" {
  name   = "fluent-bit-cloudwatch-logs"
  role   = aws_iam_role.fluent_bit.id
  policy = data.aws_iam_policy_document.fluent_bit_permissions.json
}
```

- [ ] **Step 2: Add the output**

Edit `infra/terraform/outputs.tf`, appending:

```hcl

output "fluent_bit_role_arn" {
  description = "Paste into infra/argocd/apps/eks-demo/app-fluent-bit.yaml's serviceAccount.annotations"
  value       = aws_iam_role.fluent_bit.arn
}
```

- [ ] **Step 3: Add the chart repo to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://aws.github.io/eks-charts
```

- [ ] **Step 4: Write the Application**

```yaml
# infra/argocd/apps/eks-demo/app-fluent-bit.yaml
#
# EKS's standard logging path (see docs/superpowers/specs/
# 2026-07-14-phase7-aws-rds-secrets-manager-design.md's 7.6) — a DaemonSet, deliberately with
# NO nodeSelector restricting it to the observability node group: it needs to tail container
# logs on the `apps` node group too (openlex-api/worker's own pod logs). Uses a blanket
# toleration (not scoped to the observability taint alone), the same reasoning already
# documented in infra/argocd/apps/kind/app-kube-prometheus-stack.yaml for
# prometheus-node-exporter's toleration (a scoped-only toleration previously caused a live bug
# where node-exporter silently missed the control-plane node — same class of mistake, avoided
# here from the start). Replace <FLUENT_BIT_ROLE_ARN> with `terraform output fluent_bit_role_arn`.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: aws-for-fluent-bit
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  source:
    repoURL: https://aws.github.io/eks-charts
    chart: aws-for-fluent-bit
    targetRevision: "0.1.*"
    helm:
      valuesObject:
        serviceAccount:
          create: true
          name: aws-for-fluent-bit
          annotations:
            eks.amazonaws.com/role-arn: "<FLUENT_BIT_ROLE_ARN>"
        tolerations:
          - operator: Exists
        cloudWatch:
          enabled: true
          region: us-east-1
          logGroupName: "/openlex/eks-demo/logs"
          logStreamPrefix: "fluentbit-"
          logRetentionDays: 14
        firehose:
          enabled: false
        kinesis:
          enabled: false
        elasticsearch:
          enabled: false
        resources:
          requests: { cpu: 25m, memory: 32Mi }
          limits: { cpu: 100m, memory: 64Mi }
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 5: Note the new README hand-copy target**

Edit `infra/terraform/README.md` step 4's list (from Task 6's version) to also add
`fluent_bit_role_arn` and `app-fluent-bit.yaml`.

- [ ] **Step 6: Validate**

```bash
cd infra/terraform && terraform fmt -check && terraform init -backend=false && terraform validate
```

Expected: `Success! The configuration is valid.`

Manually cross-check `app-fluent-bit.yaml`'s `cloudWatch`/`firehose`/`kinesis`/`elasticsearch`
values keys against the `aws-for-fluent-bit` chart's actual `values.yaml` (`WebFetch`
`https://github.com/aws/eks-charts/blob/master/stable/aws-for-fluent-bit/values.yaml`, record
what was checked). If the chart's real key names differ from this draft (chart versions do
drift), correct them here before committing.

- [ ] **Step 7: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-fluent-bit.yaml infra/terraform/iam_irsa_fluent_bit.tf infra/terraform/outputs.tf infra/terraform/README.md infra/argocd/projects/appproject-eks-demo.yaml
git commit -m "Add Fluent Bit for eks-demo: CloudWatch Logs (7.6)"
```

---

### Task 8: Cloud observability — Grafana, CloudWatch + X-Ray datasources (7.6c)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-grafana.yaml`,
  `infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml`,
  `infra/terraform/iam_irsa_grafana.tf`
- Modify: `infra/terraform/outputs.tf`, `infra/terraform/README.md`,
  `infra/kubernetes/overlays/eks-demo/kustomization.yaml`,
  `infra/argocd/projects/appproject-eks-demo.yaml`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability` (Task 4), the `ebs.csi.aws.com` provisioner
  (Task 4's `aws_eks_addon.ebs_csi`).
- Produces: `aws_iam_role.grafana.arn` (output `grafana_role_arn`); a Kubernetes Service named
  `grafana` on port `80` (the standalone `grafana/grafana` chart's default Service naming/port)
  — consumed by Task 9's Ingress.

- [ ] **Step 1: Write the `gp3` StorageClass**

```yaml
# infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml
#
# The aws-ebs-csi-driver EKS addon (infra/terraform/eks.tf, Task 4) installs the CSI driver
# itself but does not create a gp3 StorageClass automatically -- EKS's built-in default is
# still the older in-tree "gp2" StorageClass. Grafana's PVC below requests
# storageClassName: gp3 explicitly, so this must exist. Cluster-scoped -- kustomize's
# `namespace: openlex` transformer (this overlay's global setting) only affects namespaced
# resources, so it's safe to include here.
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
parameters:
  type: gp3
```

- [ ] **Step 2: Add it to the kustomization**

Edit `infra/kubernetes/overlays/eks-demo/kustomization.yaml`'s `resources:` list (from Task
5's version), appending `storageclass-gp3.yaml`:

```yaml
resources:
  - ../../base/api
  - ../../base/worker
  - externalsecret-openlex.yaml
  - ingress-api.yaml
  - pdb-openlex-api.yaml
  - storageclass-gp3.yaml
```

- [ ] **Step 3: Write the Grafana IRSA role**

```hcl
# infra/terraform/iam_irsa_grafana.tf
#
# IRSA role for Grafana's ServiceAccount (namespace observability, name grafana — pinned
# explicitly in app-grafana.yaml's serviceAccount.name).
data "aws_iam_policy_document" "grafana_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:observability:grafana"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "grafana" {
  name               = "${var.cluster_name}-grafana"
  assume_role_policy = data.aws_iam_policy_document.grafana_trust.json
}

# Read-only permissions matching Grafana's own documented IAM policy examples for the
# CloudWatch (core) and X-Ray (grafana-x-ray-datasource plugin) datasources.
data "aws_iam_policy_document" "grafana_permissions" {
  statement {
    effect = "Allow"
    actions = [
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListMetrics",
      "cloudwatch:DescribeAlarmsForMetric",
      "logs:GetLogEvents",
      "logs:GetLogGroupFields",
      "logs:StartQuery",
      "logs:StopQuery",
      "logs:GetQueryResults",
      "logs:GetLogRecord",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "ec2:DescribeTags",
      "ec2:DescribeInstances",
      "ec2:DescribeRegions",
      "tag:GetResources",
    ]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "xray:GetTraceSummaries",
      "xray:BatchGetTraces",
      "xray:GetTraceGraph",
      "xray:GetGroups",
      "xray:GetTimeSeriesServiceStatistics",
      "xray:GetInsightSummaries",
      "xray:GetInsight",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "grafana" {
  name   = "grafana-cloudwatch-xray-read"
  role   = aws_iam_role.grafana.id
  policy = data.aws_iam_policy_document.grafana_permissions.json
}
```

- [ ] **Step 4: Add the output**

Edit `infra/terraform/outputs.tf`, appending:

```hcl

output "grafana_role_arn" {
  description = "Paste into infra/argocd/apps/eks-demo/app-grafana.yaml's serviceAccount.annotations"
  value       = aws_iam_role.grafana.arn
}
```

- [ ] **Step 5: Add the Grafana chart repo to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://grafana.github.io/helm-charts
```

- [ ] **Step 6: Write the Application**

```yaml
# infra/argocd/apps/eks-demo/app-grafana.yaml
#
# Standalone chart (not the kube-prometheus-stack bundle kind uses) -- see 7.6's design: the
# one place kind and eks-demo stay visually consistent even though their backends differ
# completely (CloudWatch/X-Ray here vs. self-hosted Prometheus/Tempo/Jaeger/Loki on kind).
# CloudWatch is a Grafana *core* built-in datasource (no plugin needed); X-Ray needs the
# grafana-x-ray-datasource plugin installed explicitly -- a correction to the design spec's
# "no plugin gymnastics" framing (confirmed against Grafana's own plugin catalog; see the
# plan's "Note on a minor spec correction" at the top of this document).
# Replace <GRAFANA_ROLE_ARN> with `terraform output grafana_role_arn`.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: grafana
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  source:
    repoURL: https://grafana.github.io/helm-charts
    chart: grafana
    targetRevision: "8.7.*"
    helm:
      valuesObject:
        serviceAccount:
          create: true
          name: grafana
          annotations:
            eks.amazonaws.com/role-arn: "<GRAFANA_ROLE_ARN>"
        nodeSelector:
          openlex.dev/workload: observability
        tolerations:
          - key: openlex.dev/workload
            operator: Equal
            value: observability
            effect: NoSchedule
        resources:
          requests: { cpu: 50m, memory: 256Mi }
          limits: { cpu: 300m, memory: 768Mi }
        persistence:
          enabled: true
          size: 1Gi
          storageClassName: gp3
        plugins:
          - grafana-x-ray-datasource
        datasources:
          datasources.yaml:
            apiVersion: 1
            datasources:
              - name: CloudWatch
                type: cloudwatch
                access: proxy
                jsonData:
                  authType: default
                  defaultRegion: us-east-1
                isDefault: true
              - name: X-Ray
                type: grafana-x-ray-datasource
                access: proxy
                jsonData:
                  authType: default
                  defaultRegion: us-east-1
                isDefault: false
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 7: Note the new README hand-copy target**

Edit `infra/terraform/README.md` step 4's list (from Task 7's version) to also add
`grafana_role_arn` and `app-grafana.yaml`.

- [ ] **Step 8: Validate**

```bash
cd infra/terraform && terraform fmt -check && terraform init -backend=false && terraform validate
```

Expected: `Success! The configuration is valid.`

```bash
kubectl kustomize infra/kubernetes/overlays/eks-demo | grep -A3 "kind: StorageClass"
```

Expected: renders the `gp3` StorageClass with `provisioner: ebs.csi.aws.com`.

Manually cross-check `app-grafana.yaml`'s `datasources.datasources.yaml` shape and the
`grafana-x-ray-datasource` plugin's `jsonData` fields against Grafana's own provisioning docs
(`WebFetch` `https://grafana.com/docs/grafana/latest/administration/provisioning/#datasources`
and the plugin's own README on grafana.com/grafana/plugins/grafana-x-ray-datasource, record
what was checked).

- [ ] **Step 9: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-grafana.yaml infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml infra/kubernetes/overlays/eks-demo/kustomization.yaml infra/terraform/iam_irsa_grafana.tf infra/terraform/outputs.tf infra/terraform/README.md infra/argocd/projects/appproject-eks-demo.yaml
git commit -m "Add standalone Grafana for eks-demo: CloudWatch + X-Ray datasources (7.6)"
```

---

### Task 9: Ingress + oauth2-proxy for Grafana (7.9)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml`,
  `infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml`,
  `infra/argocd/apps/eks-demo/ingress-grafana.yaml`
- Modify: `infra/argocd/projects/appproject-eks-demo.yaml`, `infra/terraform/README.md`

**Interfaces:**
- Consumes: the `grafana` Service on port `80` (Task 8), the `aws-secrets-manager`
  `ClusterSecretStore` (exists today, `infra/argocd/apps/eks-demo/secretstore-aws.yaml`).
- Produces: nothing consumed by a later task.

Per the plan's "Note on resolving a real spec ambiguity" at the top of this document: this
task gates **Grafana only**. Prometheus and Jaeger do not exist as self-hosted `eks-demo`
services under 7.6's AWS-native design, so there is nothing else to put an Ingress in front of.
ArgoCD is explicitly excluded (keeps its own native login) per the Global Constraints.

- [ ] **Step 1: Add the oauth2-proxy chart repo to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://oauth2-proxy.github.io/manifests
```

- [ ] **Step 2: Write the ExternalSecret for oauth2-proxy's OAuth credentials**

```yaml
# infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml
#
# Requires the openlex/oauth2-proxy AWS Secrets Manager secret to exist by hand (JSON keys
# client_id, client_secret, cookie_secret — see infra/terraform/README.md's updated step 5) —
# a GitHub OAuth App's client ID/secret are external credentials, same category as
# ANTHROPIC_API_KEY; cookie_secret is a random 32-byte value the operator generates once
# (`python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`).
# Lives here (not infra/kubernetes/overlays/eks-demo/) and sets its own namespace explicitly
# because that overlay's kustomization.yaml sets a global `namespace: openlex` transformer that
# would silently override any namespace set on a resource routed through it — same reasoning as
# argocd-admin-externalsecret.yaml's explicit `namespace: argocd`.
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: oauth2-proxy-secrets-es
  namespace: observability
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: oauth2-proxy-secrets
    creationPolicy: Owner
  data:
    - secretKey: client-id
      remoteRef:
        key: openlex/oauth2-proxy
        property: client_id
    - secretKey: client-secret
      remoteRef:
        key: openlex/oauth2-proxy
        property: client_secret
    - secretKey: cookie-secret
      remoteRef:
        key: openlex/oauth2-proxy
        property: cookie_secret
```

- [ ] **Step 3: Write the oauth2-proxy Application**

```yaml
# infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml
#
# Gates Grafana behind a single login (7.9's design, scope-narrowed per this plan's "Note on
# resolving a real spec ambiguity" — Prometheus/Jaeger no longer exist as self-hosted
# eks-demo services; ArgoCD explicitly excluded, keeps its own native login). GitHub OAuth
# chosen over a static htpasswd-style provider (spec's own open question, resolved here):
# oauth2-proxy's htpasswd support is a secondary/basic-auth fallback, not designed as a
# standalone primary provider, and GitHub OAuth is both the more realistic cloud-native
# pattern and a natural fit for a project that already lives on GitHub. Requires a GitHub
# OAuth App registered by hand (Settings -> Developer settings -> OAuth Apps -> New OAuth App,
# callback URL https://grafana.<DOMAIN>/oauth2/callback) — a manual one-time step in the same
# category as this project's other documented manual bootstrap steps (Route53 nameservers,
# Secrets Manager seed values). `<GITHUB_USERNAME>` restricts access to a single operator
# (replace with your own GitHub username) -- without it, any GitHub-authenticated user could
# log in. Client ID/secret/cookie secret come from externalsecret-oauth2-proxy.yaml, never
# committed here.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: oauth2-proxy
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  source:
    repoURL: https://oauth2-proxy.github.io/manifests
    chart: oauth2-proxy
    targetRevision: "7.9.*"
    helm:
      valuesObject:
        config:
          existingSecret: oauth2-proxy-secrets
        extraArgs:
          provider: github
          github-user: "<GITHUB_USERNAME>"
          email-domain: "*"
          upstreams: static://202
          http-address: "0.0.0.0:4180"
          cookie-secure: "true"
          cookie-samesite: "lax"
          set-xauthrequest: "true"
        resources:
          requests: { cpu: 25m, memory: 32Mi }
          limits: { cpu: 100m, memory: 64Mi }
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 4: Write the Grafana Ingress**

```yaml
# infra/argocd/apps/eks-demo/ingress-grafana.yaml
#
# nginx.ingress.kubernetes.io/auth-url + auth-signin gate access via oauth2-proxy
# (app-oauth2-proxy.yaml) -- the standard, documented ingress-nginx + oauth2-proxy
# integration pattern. Lives here, not infra/kubernetes/overlays/eks-demo/, for the same
# namespace-transformer reason as externalsecret-oauth2-proxy.yaml above. Replace <DOMAIN>
# with the real demo domain.
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana
  namespace: observability
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-staging
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/auth-url: "https://grafana.<DOMAIN>/oauth2/auth"
    nginx.ingress.kubernetes.io/auth-signin: "https://grafana.<DOMAIN>/oauth2/start?rd=$scheme://$host$request_uri"
    nginx.ingress.kubernetes.io/auth-response-headers: "X-Auth-Request-User, X-Auth-Request-Email"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - grafana.<DOMAIN>
      secretName: grafana-tls
  rules:
    - host: grafana.<DOMAIN>
      http:
        paths:
          - path: /oauth2
            pathType: Prefix
            backend:
              service:
                name: oauth2-proxy
                port:
                  number: 4180
          - path: /
            pathType: Prefix
            backend:
              service:
                name: grafana
                port:
                  number: 80
```

- [ ] **Step 5: Update README.md's setup sequence**

Edit `infra/terraform/README.md`'s step 5 (from Task 1's version) to add, after the existing
`openlex/app`/`openlex/argocd-admin` bullets:

```
   Also create `openlex/oauth2-proxy` (JSON keys `client_id`, `client_secret`, `cookie_secret`)
   after registering a GitHub OAuth App (see
   `infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml`'s header comment for the exact steps).
```

- [ ] **Step 6: Cross-check the integration against oauth2-proxy's own docs**

`WebFetch` `https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview` and
`.../configuration/providers/github`. Confirm `upstreams: static://202` is the documented
auth-only-mode idiom, and that `provider: github` + `github-user` is the correct flag for
restricting to a single GitHub user. Record what was checked in the task report.

- [ ] **Step 7: Validate the Ingress YAML syntax**

```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/ingress-grafana.yaml')))" && echo OK
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml')))" && echo OK
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml')))" && echo OK
```

Expected: `OK` printed 3 times, no exceptions.

- [ ] **Step 8: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml infra/argocd/apps/eks-demo/ingress-grafana.yaml infra/argocd/projects/appproject-eks-demo.yaml infra/terraform/README.md
git commit -m "Add oauth2-proxy + Ingress gating Grafana for eks-demo (7.9)"
```

---

### Task 10: Static CDN — Terraform: S3 + CloudFront + ACM + GitHub OIDC role (7.8b)

**Files:**
- Create: `infra/terraform/static-site.tf`, `infra/terraform/iam_oidc_github_actions.tf`
- Modify: `infra/terraform/providers.tf`, `infra/terraform/versions.tf`,
  `infra/terraform/variables.tf`, `infra/terraform/outputs.tf`,
  `infra/kubernetes/overlays/eks-demo/ingress-api.yaml`

**Interfaces:**
- Consumes: `aws_route53_zone.demo` (`infra/terraform/route53.tf`, exists today),
  `var.domain_name` (exists today).
- Produces: `aws_s3_bucket.web`, `aws_cloudfront_distribution.web`,
  `aws_iam_role.github_actions_deploy_web.arn` — all three consumed by Task 11's
  `deploy-static.yml` (as `terraform output web_bucket_name`, `cloudfront_distribution_id`,
  `github_actions_deploy_web_role_arn`, hand-copied into GitHub Actions repository variables).

- [ ] **Step 1: Add the `tls` provider**

Edit `infra/terraform/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}
```

- [ ] **Step 2: Add the `us-east-1` provider alias**

Edit `infra/terraform/providers.tf`, appending:

```hcl

# CloudFront/ACM specifically require us-east-1 regardless of var.region — see static-site.tf's
# aws_acm_certificate.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "openlex"
      Environment = "eks-demo"
      ManagedBy   = "terraform"
    }
  }
}
```

- [ ] **Step 3: Add the `github_repository` variable**

Edit `infra/terraform/variables.tf`, appending:

```hcl

variable "github_repository" {
  description = "GitHub \"owner/repo\" this project lives in — scopes the GitHub Actions OIDC trust policy"
  type        = string
  default     = "rozdolsky33/OpenLex"
}
```

- [ ] **Step 4: Write `static-site.tf`**

```hcl
# infra/terraform/static-site.tf
#
# apps/web's production build (vite build -> static dist/) served via S3 + CloudFront instead
# of the ingress-nginx -> web-pod dev-server routing kind/compose use — see
# docs/superpowers/specs/2026-07-14-phase7-aws-rds-secrets-manager-design.md's 7.8.
# app.<domain> moves here; api.<domain> (infra/kubernetes/overlays/eks-demo/ingress-api.yaml)
# stays on ingress-nginx, unchanged in kind.

resource "random_id" "web_bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "web" {
  bucket = "${var.cluster_name}-web-${random_id.web_bucket_suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CloudFront reaches the bucket via Origin Access Control, not a public bucket policy or the
# older Origin Access Identity — OAC is AWS's current recommended approach.
resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.cluster_name}-web-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "web_bucket_policy" {
  statement {
    sid       = "AllowCloudFrontOAC"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = data.aws_iam_policy_document.web_bucket_policy.json
}

# ACM certificates for CloudFront must be requested in us-east-1 specifically, regardless of
# var.region -- a CloudFront-specific AWS requirement, independent of where the rest of this
# infrastructure lives (var.region already defaults to us-east-1 today, but this alias makes
# it correct even if that ever changes).
resource "aws_acm_certificate" "web" {
  provider          = aws.us_east_1
  domain_name       = "app.${var.domain_name}"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "web_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.web.domain_validation_options : dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }

  zone_id = aws_route53_zone.demo.zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "web" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.web.arn
  validation_record_fqdns = [for r in aws_route53_record.web_cert_validation : r.fqdn]
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  default_root_object = "index.html"
  aliases             = ["app.${var.domain_name}"]
  # price_class deliberately left unset (defaults to PriceClass_All) — CloudFront's edge
  # network is global by default, Europe included, with no special per-region config needed;
  # explicitly restricting to a smaller price class would work against that.

  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_id                = "web-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    allowed_methods         = ["GET", "HEAD"]
    cached_methods           = ["GET", "HEAD"]
    target_origin_id        = "web-s3"
    viewer_protocol_policy  = "redirect-to-https"
    cache_policy_id         = "658327ea-f89d-4fab-a63d-7e88639e58f6" # AWS-managed "CachingOptimized" policy
  }

  # apps/web is a client-side-routed SPA (React) -- a direct hit on e.g. /login must still
  # serve index.html (200), not CloudFront's default S3 404/403, or a browser refresh on any
  # non-root route breaks.
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.web.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_route53_record" "app" {
  zone_id = aws_route53_zone.demo.zone_id
  name    = "app.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
    evaluate_target_health = false
  }
}
```

- [ ] **Step 5: Write the GitHub OIDC IAM role**

```hcl
# infra/terraform/iam_oidc_github_actions.tf
#
# Lets .github/workflows/deploy-static.yml (Task 11) authenticate to AWS via GitHub's OIDC
# federation -- no static AWS access keys in GitHub secrets, matching this project's "no
# static cloud credentials" precedent (IRSA everywhere else). Assumes no GitHub Actions OIDC
# provider already exists in this AWS account -- this project's own AWS account has never had
# any Terraform apply of any kind (see "Explicitly out of scope"), so this is safe to create
# fresh.
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

# Scoped to pushes on main only (deploy-static.yml's own trigger) -- a PR branch's workflow
# run could never assume this role, even if it tried.
data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy_web" {
  name               = "${var.cluster_name}-github-actions-deploy-web"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

data "aws_iam_policy_document" "github_actions_deploy_web_permissions" {
  statement {
    effect  = "Allow"
    actions = ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.web.arn,
      "${aws_s3_bucket.web.arn}/*",
    ]
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.web.arn]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy_web" {
  name   = "github-actions-deploy-web"
  role   = aws_iam_role.github_actions_deploy_web.id
  policy = data.aws_iam_policy_document.github_actions_deploy_web_permissions.json
}
```

- [ ] **Step 6: Add outputs**

Edit `infra/terraform/outputs.tf`, appending:

```hcl

output "web_bucket_name" {
  description = "Paste into the GitHub repo's OPENLEX_WEB_BUCKET Actions variable"
  value       = aws_s3_bucket.web.id
}

output "cloudfront_distribution_id" {
  description = "Paste into the GitHub repo's OPENLEX_CLOUDFRONT_DISTRIBUTION_ID Actions variable"
  value       = aws_cloudfront_distribution.web.id
}

output "github_actions_deploy_web_role_arn" {
  description = "Paste into the GitHub repo's GITHUB_ACTIONS_DEPLOY_WEB_ROLE_ARN Actions variable"
  value       = aws_iam_role.github_actions_deploy_web.arn
}
```

- [ ] **Step 7: Split the domain — `api.<DOMAIN>` replaces `app.<DOMAIN>` for the API ingress**

Edit `infra/kubernetes/overlays/eks-demo/ingress-api.yaml`:

```yaml
# Replace <DOMAIN> with the real demo domain (e.g. openlex-demo.example.com) before applying.
# Start with cluster-issuer: letsencrypt-staging (see infra/argocd/apps/eks-demo/), switch to
# letsencrypt-prod once the staging issuance succeeds end-to-end (avoids burning Let's
# Encrypt's production rate limit while debugging HTTP-01 reachability).
#
# api.<DOMAIN> (not app.<DOMAIN>) -- app.<DOMAIN> now goes to CloudFront/S3 for apps/web's
# static build instead (infra/terraform/static-site.tf, 7.8). This ingress only ever routed
# to the openlex-api Service directly (there was no separate web ingress before this), so the
# fix is a host-value rename, not a routing change.
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: openlex-api
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-staging
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.<DOMAIN>
      secretName: openlex-api-tls
  rules:
    - host: api.<DOMAIN>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: openlex-api
                port:
                  name: http
```

- [ ] **Step 8: Validate**

```bash
cd infra/terraform
terraform fmt -check
terraform init -backend=false
terraform validate
```

Expected: `Success! The configuration is valid.`

```bash
kubectl kustomize infra/kubernetes/overlays/eks-demo | grep "host:"
```

Expected: only `api.<DOMAIN>` appears (confirm `app.<DOMAIN>` is gone from this file).

- [ ] **Step 9: Commit**

```bash
git add infra/terraform/static-site.tf infra/terraform/iam_oidc_github_actions.tf infra/terraform/providers.tf infra/terraform/versions.tf infra/terraform/variables.tf infra/terraform/outputs.tf infra/kubernetes/overlays/eks-demo/ingress-api.yaml
git commit -m "Add S3 + CloudFront static hosting for apps/web, GitHub OIDC deploy role (7.8)"
```

---

### Task 11: Static CDN — apps/web production build + deploy-static.yml (7.8a + 7.8c)

**Files:**
- Create: `.github/workflows/deploy-static.yml`
- Modify: `infra/terraform/README.md`

**Interfaces:**
- Consumes: `apps/web`'s existing `npm run build` script (`package.json`, unchanged — already
  produces a real `dist/`, confirmed working during this plan's own research, see Step 1),
  Task 10's `web_bucket_name`/`cloudfront_distribution_id`/`github_actions_deploy_web_role_arn`
  outputs.
- Produces: nothing consumed by a later task.

- [ ] **Step 1: Confirm the production build works locally (no AWS needed)**

```bash
cd apps/web
VITE_API_BASE_URL=https://api.example.com npm run build
```

Expected: `tsc -b && vite build` completes with no errors, printing a `dist/` asset summary
(`dist/index.html`, `dist/assets/index-*.css`, `dist/assets/index-*.js`). This already passes
as-is today — no code changes needed in `apps/web` itself.

```bash
grep -o "api.example.com" dist/assets/*.js
```

Expected: prints `api.example.com` — confirms `VITE_API_BASE_URL` really is baked into the
built JS bundle at build time (not read at runtime, unlike kind/compose's dev-server path).

```bash
rm -rf dist
```

(`dist/` is already git-ignored — see root `.gitignore`'s `dist/` entry — so this is just local
cleanup, not required for the commit to be clean, but keeps the working tree tidy.)

- [ ] **Step 2: Write the workflow**

```yaml
# .github/workflows/deploy-static.yml
name: deploy-static

on:
  push:
    branches: [main]
    paths:
      - "apps/web/**"
      - ".github/workflows/deploy-static.yml"

permissions:
  id-token: write # required for GitHub OIDC -> AWS
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    defaults:
      run:
        working-directory: apps/web
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version-file: apps/web/.nvmrc
          cache: npm
          cache-dependency-path: apps/web/package-lock.json

      - run: npm ci

      - name: Build (production, API base URL baked in)
        env:
          VITE_API_BASE_URL: https://api.${{ vars.OPENLEX_DOMAIN }}
        run: npm run build

      - name: Configure AWS credentials (OIDC, no static keys)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.GITHUB_ACTIONS_DEPLOY_WEB_ROLE_ARN }}
          aws-region: us-east-1

      - name: Sync to S3
        run: aws s3 sync dist/ "s3://${{ vars.OPENLEX_WEB_BUCKET }}" --delete

      - name: Invalidate CloudFront
        run: aws cloudfront create-invalidation --distribution-id "${{ vars.OPENLEX_CLOUDFRONT_DISTRIBUTION_ID }}" --paths "/*"
```

- [ ] **Step 3: Document the new repository variables in the README**

Edit `infra/terraform/README.md`, adding a new subsection after "First-time setup" (renumbering
not required — this is additive):

```markdown
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
```

- [ ] **Step 4: Validate the workflow YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-static.yml'))" && echo OK
```

Expected: `OK`, no exceptions.

Manually cross-check the `aws-actions/configure-aws-credentials@v4` step's `role-to-assume`/
`aws-region` inputs and the `permissions: id-token: write` requirement against GitHub's own
OIDC-with-AWS documentation (`WebFetch`
`https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services`,
record what was checked).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy-static.yml infra/terraform/README.md
git commit -m "Add deploy-static.yml: apps/web production build to S3 + CloudFront (7.8)"
```

---

### Task 12: Terraform remote state (7.4)

**Files:**
- Modify: `infra/terraform/backend.tf`, `infra/terraform/README.md`, `.gitignore`
- Create: `infra/terraform/backend.hcl.example`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing consumed by a later task — this is deliberately the last Terraform task
  (see the note below).

**Why this task runs last, not "early/alongside" Task 1 as the spec's own risk note
suggests:** that risk note is about *live deployment* ordering (once someone actually runs
`terraform apply` for real, the RDS-generated password ends up in state, so remote state should
exist before/alongside that real apply). This phase never runs `terraform apply` at all — no
state file, sensitive or not, is ever created during this implementation. Sequencing this task
last instead means every earlier task's `terraform init -backend=false && terraform validate`
keeps working throughout the plan without ever needing a real S3 bucket; had `backend.tf`
switched to a real `backend "s3" {}` block first, every subsequent task would need to either
fight Terraform's "backend configuration changed, re-run init" error or also pass
`-backend=false`, for no real benefit this early. The README documents the correct *live*
ordering (remote state before/alongside a real `terraform apply` of `rds.tf`) for whoever
deploys this for real later.

- [ ] **Step 1: Uncomment and parameterize `backend.tf`**

```hcl
# infra/terraform/backend.tf
#
# Real bucket/key/region/dynamodb_table values are supplied via
# `terraform init -backend-config=backend.hcl` (copy backend.hcl.example -> backend.hcl and
# fill in real values — never commit backend.hcl itself, see .gitignore) rather than
# terraform.tfvars, because Terraform backend blocks cannot reference variables or
# terraform.tfvars at all — this partial-configuration pattern is the standard way to keep
# real bucket names out of a committed file while still using a real S3 backend.
#
# See README.md's "Remote state" section for the one-time bootstrap (the S3 bucket + DynamoDB
# lock table this backend needs can't be created by the same Terraform config that needs them
# to exist first — the classic remote-state chicken-and-egg).
terraform {
  backend "s3" {
    encrypt = true
  }
}
```

- [ ] **Step 2: Write `backend.hcl.example`**

```hcl
# infra/terraform/backend.hcl.example
#
# Copy to backend.hcl (git-ignored), fill in real values, then:
#   terraform init -backend-config=backend.hcl -migrate-state
bucket         = "<your-tfstate-bucket>"
key            = "openlex/eks-demo/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "<your-tflock-table>"
```

- [ ] **Step 3: Protect local Terraform artifacts in `.gitignore`**

Edit `.gitignore`, appending:

```

# Terraform (infra/terraform/) — local plan/state artifacts and real backend/tfvars values,
# never committed (see infra/terraform/README.md's "Remote state" section and
# terraform.tfvars.example/backend.hcl.example for the committed templates).
infra/terraform/.terraform/
infra/terraform/*.tfstate*
infra/terraform/backend.hcl
infra/terraform/terraform.tfvars
```

- [ ] **Step 4: Add the "Remote state" section to `infra/terraform/README.md`**

Add a new section after "## State" (the existing section, which currently says "Local state by
default... Switch to an S3+DynamoDB backend once that stops being true" — leave that section's
text as-is, since it's still an accurate description of the *default*; this is additive):

```markdown
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
```

- [ ] **Step 5: Validate**

```bash
cd infra/terraform
terraform fmt -check
terraform init -backend=false
terraform validate
```

Expected: `Success! The configuration is valid.` (`-backend=false` skips backend
initialization entirely, regardless of what `backend.tf` now declares — this is the one task
in the plan that could not use a real `terraform init` against `backend.tf` as written, since
there is no real S3 bucket to point it at; this is consistent with the phase's own "no live
deployment" scope, not a gap specific to this task.)

- [ ] **Step 6: Commit**

```bash
git add infra/terraform/backend.tf infra/terraform/backend.hcl.example infra/terraform/README.md .gitignore
git commit -m "Configure Terraform S3 remote state backend, document bootstrap (7.4)"
```

---

## Final whole-branch review — explicit 7.3 check

7.3 (environment isolation) has no dedicated task — it's a guarantee, not new code. Include
this exact check in the final whole-branch review's dispatch:

```bash
git diff main...HEAD --stat -- scripts/kind-secrets-bootstrap.sh infra/kubernetes/overlays/kind/ infra/argocd/apps/kind/ infra/kubernetes/kind/ docker-compose.yml
```

Expected: **empty output** — zero changes to any of these paths. If this shows any diff, that
is a real finding (a violation of the phase's own explicit "local kind never gains any path to
real AWS resources, not even an optional one" constraint), not a stylistic nit.

## Self-Review

**Spec coverage:** 7.1 → Tasks 1-2. 7.2 → Task 3. 7.3 → final-review check above (no
dedicated task, by design — no new code). 7.4 → Task 12. 7.5 → folded into Task 1's
`aws_db_instance` backup arguments. 7.6 → Tasks 6-8. 7.7 → Tasks 4-5. 7.8 → Tasks 10-11. 7.9 →
Task 9.

**Placeholder scan:** no TBD/TODO markers; the two `<PLACEHOLDER>` conventions used
(`<DOMAIN>`, `<GITHUB_USERNAME>`, `<*_ROLE_ARN>`) are the project's own established, real
convention for values a human hand-copies after `terraform apply` or hand-registers externally
(e.g. `<ACME_EMAIL>` in the existing `clusterissuer-letsencrypt.yaml`) — not unresolved plan
gaps.

**Type/naming consistency:** `openlex.dev/workload` taint/label key and `observability`/`apps`
values are identical across Tasks 4, 5, 6, 7, 8 and kind's existing files (verified by Task 5
Step 5's `grep`). Secret/ServiceAccount names referenced across Terraform (`iam_irsa_*.tf`) and
ArgoCD (`app-*.yaml`) match 1:1: `otel-collector`/`observability`, `aws-for-fluent-bit`/
`observability`, `grafana`/`observability`, `ebs-csi-controller-sa`/`kube-system`. `DATABASE_URL`
scheme (`postgresql+asyncpg://`) is consistent between Task 1's `rds.tf` and Task 2's
`job.yaml` (which explicitly strips `+asyncpg` before handing the URL to `psql`).

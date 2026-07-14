# Phase 7 — AWS RDS + Secrets Manager + Node Topology + CDN + Ingress/Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build (not deploy) the complete Terraform + Kubernetes/ArgoCD infrastructure-as-code
for `eks-demo`'s real cloud-production path — RDS Postgres, verified Secrets Manager/External
Secrets Operator wiring, a two-node-group topology mirroring kind's observability/apps
separation, that same self-hosted observability stack (kube-prometheus-stack + Tempo + Jaeger
+ Loki + Promtail) running for real on it, S3+CloudFront static hosting for `apps/web`,
ingress + oauth2-proxy auth for Grafana (Prometheus/Jaeger stay port-forward-only), and
Terraform remote state — all `terraform validate`-clean and ready to deploy, with zero live AWS
deployment in this phase.

**Architecture:** Extends the existing (never-deployed) `infra/terraform/` + `infra/argocd/` +
`infra/kubernetes/overlays/eks-demo/` scaffolding in place — no new top-level directories.
Every new Terraform resource follows the file-per-concern convention already established there
(`ecr.tf`, `iam_irsa_external_dns.tf`, etc.); every new ArgoCD Application follows the
sync-wave pattern already used by `external-dns`/`external-secrets`, and every observability
Application is a near-literal copy of its `infra/argocd/apps/kind/` counterpart — same chart,
same shared `infra/monitoring/*/values-base.yaml` file, same `openlex.dev/workload`
taint/label/toleration strings — because `eks-demo` runs the *same* observability stack as
kind, just on real multi-AZ, EBS-backed compute instead of kind's single shared Docker daemon.

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
  gate in this phase; Prometheus and Jaeger (no built-in auth) get **no Ingress at all**, only
  a port-forward script (Task 10).
- **Every eks-demo observability Application mirrors its kind counterpart** (same chart
  version, same shared `infra/monitoring/*/values-base.yaml` file via the `$values` multi-source
  reference) — the only intentional differences are `project: openlex-eks-demo` (not
  `openlex-kind`), the values-repo source's `targetRevision: main` (not `develop` — `eks-demo`
  tracks `main`, `develop` is kind/dev-only, see `docs/infrastructure/
  dev-workflow-and-branching.md`), and `postgres-exporter`'s DSN (RDS, not the in-cluster
  Service). No AWS-native exporters (X-Ray/CloudWatch/Fluent Bit) are built this phase — see
  the design spec's 7.6 "Future enhancement" note.
- **CloudFront's ACM certificate must use a `us-east-1` provider alias** regardless of
  `var.region`'s value.
- Every new IRSA `ServiceAccount` name is pinned explicitly in the consuming Application's Helm
  values (never left to the chart default), matching `external-secrets`'/`external-dns`'s
  existing pattern, so each new IAM role's trust-policy `sub` condition actually matches.
- Every new ArgoCD `Application` that pulls from a Helm chart repo not already in
  `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos` must add that repo URL, or
  ArgoCD will refuse to sync it (`AppProject` enforcement).

---

## Note on the 7.6/7.9 revision (self-hosted, not AWS-native)

This plan was originally written against a 7.6/7.9 design built on AWS-native observability
(X-Ray/CloudWatch/a standalone Grafana with oauth2-proxy in front of Grafana+Prometheus+Jaeger).
That design was reversed after direct feedback, before any task in this plan was executed: the
design spec's 7.6 and 7.9 sections were revised in place (see their own "Revised" headers) to
mirror kind's self-hosted stack (kube-prometheus-stack + Tempo + Jaeger + Loki + Promtail)
instead, with AWS-native observability moved to a documented future-enhancement note. Tasks
6-10 below implement the revised design directly — there is no earlier AWS-native version of
these tasks to reconcile against; this is simply what Tasks 6-10 are. Two practical
consequences worth stating up front:

- **No new IAM/IRSA roles are needed for observability at all.** Every self-hosted component
  (OTel Collector, Tempo, Jaeger, Loki, Promtail, kube-prometheus-stack, postgres-exporter)
  talks only to other in-cluster Services or (for postgres-exporter) RDS over the network via
  the security group Task 1 already opens — none of them call an AWS API. This is a real
  simplification relative to the original AWS-native design, not an oversight.
- **Grafana dashboards need no CloudWatch-flavored parallel versions.** Because `eks-demo` now
  queries the same Prometheus/Tempo/Jaeger/Loki backends kind does, the existing PromQL/LogQL/
  TraceQL dashboard JSON under `infra/monitoring/grafana/dashboards/` works unchanged — this
  also resolves the open question the original 7.6 draft flagged and never answered.

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
- **Task 5:** `infra/kubernetes/overlays/eks-demo/{patch-resources.yaml,pdb-openlex-api.yaml,
  storageclass-gp3.yaml}` (new), `infra/kubernetes/overlays/eks-demo/kustomization.yaml`
  (modified)
- **Task 6:** `infra/argocd/apps/eks-demo/{app-otel-collector.yaml,app-tempo.yaml,
  app-jaeger.yaml}` (new), `infra/argocd/projects/appproject-eks-demo.yaml` (modified)
- **Task 7:** `infra/argocd/apps/eks-demo/{app-loki.yaml,app-promtail.yaml}` (new — no new
  `sourceRepos` entry, `grafana.github.io/helm-charts` already added by Task 6)
- **Task 8:** `infra/argocd/apps/eks-demo/{app-kube-prometheus-stack.yaml,
  app-observability-dashboards.yaml}` (new),
  `infra/argocd/projects/appproject-eks-demo.yaml` (modified)
- **Task 9:** `infra/argocd/apps/eks-demo/app-postgres-exporter.yaml` (new)
- **Task 10:** `infra/argocd/apps/eks-demo/{app-oauth2-proxy.yaml,
  externalsecret-oauth2-proxy.yaml,ingress-grafana.yaml}` (new),
  `scripts/eks-demo-observability-port-forward.sh` (new),
  `infra/argocd/projects/appproject-eks-demo.yaml`, `infra/terraform/README.md` (modified)
- **Task 11:** `infra/terraform/static-site.tf` (new),
  `infra/terraform/iam_oidc_github_actions.tf` (new), `infra/terraform/providers.tf`,
  `infra/terraform/versions.tf`, `infra/terraform/variables.tf`, `infra/terraform/outputs.tf`,
  `infra/kubernetes/overlays/eks-demo/ingress-api.yaml` (all modified)
- **Task 12:** `.github/workflows/deploy-static.yml` (new), `infra/terraform/README.md`
  (modified)
- **Task 13:** `infra/terraform/backend.tf`, `infra/terraform/backend.hcl.example` (new),
  `infra/terraform/README.md`, `.gitignore` (modified)

Note: `infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml` (the `gp3` `StorageClass`
Tempo/Loki's PVCs rely on via the default-class annotation) moves to **Task 5** now — it's a
plain Kubernetes overlay resource, so it belongs with that task's other new K8s YAML and
`kustomization.yaml` edit, not bundled into an observability Application task. Task 6 (Tempo)
and Task 7 (Loki) both need it to already exist.

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
  (name `openlex/app` — Task 3's `dataFrom.extract` review and Task 9's `postgres-exporter`
  both depend on this name and its `DATABASE_URL`/`POSTGRES_EXPORTER_DSN` keys existing, via
  the existing `externalsecret-openlex.yaml`'s `dataFrom.extract`; no other `.tf` file
  references this resource by name).

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

# Writes DATABASE_URL and POSTGRES_EXPORTER_DSN on the *first* apply -- the other keys this
# secret needs (ANTHROPIC_API_KEY, NY_OPEN_LEG_API_KEY, JWT_SECRET_KEY, DEMO_*) are external
# credentials Terraform has no business generating, and must be merged in by hand afterward
# (see infra/terraform/README.md's updated step 5). lifecycle.ignore_changes on secret_string
# means that manual merge survives every subsequent `terraform apply` -- without it,
# re-applying this resource would silently overwrite the merged secret back down to just these
# two keys, deleting the other 4. The real tradeoff: after the first apply, Terraform also
# stops updating DATABASE_URL/POSTGRES_EXPORTER_DSN themselves on this secret (e.g. if the DB
# were ever recreated with a new generated password) -- acceptable here since recreating
# aws_db_instance.openlex is itself a rare, deliberate, manually-supervised event, not
# something that happens silently.
#
# POSTGRES_EXPORTER_DSN mirrors scripts/kind-secrets-bootstrap.sh's existing derivation for
# the same purpose (Task 9, 7.6 revised: prometheus-postgres-exporter's `config.datasourceSecret`
# needs a plain libpq DSN, not SQLAlchemy's `+asyncpg` scheme DATABASE_URL uses) -- adjusted to
# `sslmode=require` since RDS, unlike kind's local Postgres, supports real TLS.
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL          = "postgresql+asyncpg://${var.db_username}:${random_password.rds.result}@${aws_db_instance.openlex.address}:5432/${var.db_name}"
    POSTGRES_EXPORTER_DSN = "postgresql://${var.db_username}:${random_password.rds.result}@${aws_db_instance.openlex.address}:5432/${var.db_name}?sslmode=require"
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
    # ArgoCD + the full self-hosted observability stack (kube-prometheus-stack, Tempo, Jaeger,
    # Loki, Promtail, OTel Collector — see docs/superpowers/specs/
    # 2026-07-14-phase7-aws-rds-secrets-manager-design.md's 7.6, revised) get their own node
    # group, tainted so nothing else schedules there by accident.
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
  description = "Instance type for the `observability` node group — larger than apps: kube-prometheus-stack + Tempo + Jaeger + Loki + Promtail + OTel Collector + ArgoCD together need more headroom"
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

- [ ] **Step 6: Write the `gp3` StorageClass**

Tasks 6/7 (Tempo, Loki) need real persistent storage — kind's equivalent PVCs bind against
kind's default `standard` StorageClass automatically; `eks-demo` needs the same "just works"
default, backed by the `aws-ebs-csi-driver` addon Task 4 already installed:

```yaml
# infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml
#
# The aws-ebs-csi-driver EKS addon (infra/terraform/eks.tf, Task 4) installs the CSI driver
# itself but does not create a gp3 StorageClass automatically -- EKS's built-in default is
# still the older in-tree "gp2" StorageClass. Marked as the cluster's default StorageClass so
# Tempo's and Loki's PVCs (Tasks 6/7) bind automatically without needing an explicit
# storageClassName override in either chart's values -- the same "just works" experience kind
# gets from its own default `standard` StorageClass. Cluster-scoped -- kustomize's
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

Add it to `infra/kubernetes/overlays/eks-demo/kustomization.yaml`'s `resources:` list (from
Step 3 above), appending `storageclass-gp3.yaml`:

```yaml
resources:
  - ../../base/api
  - ../../base/worker
  - externalsecret-openlex.yaml
  - ingress-api.yaml
  - pdb-openlex-api.yaml
  - storageclass-gp3.yaml
```

```bash
kubectl kustomize infra/kubernetes/overlays/eks-demo | grep -A3 "kind: StorageClass"
```

Expected: renders the `gp3` `StorageClass` with `provisioner: ebs.csi.aws.com`.

- [ ] **Step 7: Commit**

```bash
git add infra/kubernetes/overlays/eks-demo/patch-resources.yaml infra/kubernetes/overlays/eks-demo/pdb-openlex-api.yaml infra/kubernetes/overlays/eks-demo/storageclass-gp3.yaml infra/kubernetes/overlays/eks-demo/kustomization.yaml
git commit -m "Add eks-demo hard anti-affinity + PDB + gp3 StorageClass for the apps node group (7.7)"
```

---

### Task 6: Observability — OTel Collector, Tempo, Jaeger (traces, mirrors kind) (7.6 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-otel-collector.yaml`,
  `infra/argocd/apps/eks-demo/app-tempo.yaml`, `infra/argocd/apps/eks-demo/app-jaeger.yaml`
- Modify: `infra/argocd/projects/appproject-eks-demo.yaml`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability` taint/label (Task 4), the `gp3`
  `StorageClass` (Task 5), the shared `infra/monitoring/{otel-collector,tempo,jaeger}/
  values-base.yaml` files (exist today, already written to be consumed by "the kind
  Application and any future eks-demo Application").
- Produces: an `otel-collector-opentelemetry-collector` Service (OTLP receiver, ports
  4317/4318) in the `observability` namespace — no later task in this plan sends traces to it
  directly (apps/api's own OTel wiring is out of this plan's scope, unchanged from what already
  exists), but it's the collector every future app deployment on `eks-demo` will point at.

These three are a near-literal copy of their kind counterparts — same chart/version, same
`$values` file reference, only `project`/`targetRevision` differ. Read each kind file first so
the diff is obvious.

- [ ] **Step 1: Add the OTel Collector, Tempo, and Jaeger chart repos to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://open-telemetry.github.io/opentelemetry-helm-charts
    - https://grafana.github.io/helm-charts
    - https://jaegertracing.github.io/helm-charts
```

- [ ] **Step 2: Write the OTel Collector Application**

Read `infra/argocd/apps/kind/app-otel-collector.yaml` first (identical shape, `project` and
`targetRevision` differ only):

```yaml
# infra/argocd/apps/eks-demo/app-otel-collector.yaml
#
# Identical to infra/argocd/apps/kind/app-otel-collector.yaml — same chart/version/
# values-base.yaml, same otlp/tempo + otlp/jaeger dual export (no AWS exporters; see the
# plan's "Note on the 7.6/7.9 revision"). Only `project` and the values-repo source's
# `targetRevision` (main, not develop — eks-demo tracks main) differ.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: otel-collector
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://open-telemetry.github.io/opentelemetry-helm-charts
      chart: opentelemetry-collector
      targetRevision: "0.165.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/otel-collector/values-base.yaml
        valuesObject:
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
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
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

- [ ] **Step 3: Write the Tempo Application**

Read `infra/argocd/apps/kind/app-tempo.yaml` first:

```yaml
# infra/argocd/apps/eks-demo/app-tempo.yaml
#
# Identical to infra/argocd/apps/kind/app-tempo.yaml. persistence.enabled/size (in the shared
# values-base.yaml) binds against the gp3 StorageClass (Task 5's default-class annotation) --
# no storageClassName override needed here, same as kind relying on its own default `standard`
# StorageClass.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tempo
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://grafana.github.io/helm-charts
      chart: tempo
      targetRevision: "1.24.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/tempo/values-base.yaml
        valuesObject:
          nodeSelector:
            openlex.dev/workload: observability
          tolerations:
            - key: openlex.dev/workload
              operator: Equal
              value: observability
              effect: NoSchedule
          tempo:
            memBallastSizeMbs: 128
            resources:
              requests: { cpu: 50m, memory: 512Mi }
              limits: { cpu: 500m, memory: 1536Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
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

- [ ] **Step 4: Write the Jaeger Application**

Read `infra/argocd/apps/kind/app-jaeger.yaml` first:

```yaml
# infra/argocd/apps/eks-demo/app-jaeger.yaml
#
# Identical to infra/argocd/apps/kind/app-jaeger.yaml — in-memory storage (comparison backend,
# data does not survive a pod restart), no PVC, no StorageClass dependency.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: jaeger
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://jaegertracing.github.io/helm-charts
      chart: jaeger
      targetRevision: "4.11.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/jaeger/values-base.yaml
        valuesObject:
          jaeger:
            nodeSelector:
              openlex.dev/workload: observability
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
            resources:
              requests: { cpu: 50m, memory: 128Mi }
              limits: { cpu: 200m, memory: 256Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
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

- [ ] **Step 5: Validate**

```bash
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-otel-collector.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-otel-collector.yaml)
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-tempo.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-tempo.yaml)
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-jaeger.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-jaeger.yaml)
```

Expected: the only differences per file are the header comment, `project: openlex-eks-demo`
(vs. `openlex-kind`), and `targetRevision: main` (vs. `develop`) on the values-repo source.
Anything else differing is a real mistake — fix it before committing.

```bash
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['infra/argocd/apps/eks-demo/app-otel-collector.yaml','infra/argocd/apps/eks-demo/app-tempo.yaml','infra/argocd/apps/eks-demo/app-jaeger.yaml']]" && echo OK
```

Expected: `OK`, no exceptions.

- [ ] **Step 6: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-otel-collector.yaml infra/argocd/apps/eks-demo/app-tempo.yaml infra/argocd/apps/eks-demo/app-jaeger.yaml infra/argocd/projects/appproject-eks-demo.yaml
git commit -m "Mirror kind's OTel Collector/Tempo/Jaeger onto eks-demo (7.6 revised)"
```

---

### Task 7: Observability — Loki, Promtail (logs, mirrors kind) (7.6 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-loki.yaml`, `infra/argocd/apps/eks-demo/app-promtail.yaml`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability`/`apps` taints/labels (Task 4), the `gp3`
  `StorageClass` (Task 5), `grafana.github.io/helm-charts` (already in the AppProject's
  `sourceRepos` from Task 6 — Loki uses the same repo Tempo does).
- Produces: a `loki` Service (push/query API, port 3100) in the `observability` namespace —
  consumed by Task 8's Grafana (as a datasource) and by Promtail (this task).

Both are a near-literal copy of their kind counterparts. Read each kind file first.

- [ ] **Step 1: Write the Loki Application**

Read `infra/argocd/apps/kind/app-loki.yaml` first:

```yaml
# infra/argocd/apps/eks-demo/app-loki.yaml
#
# Identical to infra/argocd/apps/kind/app-loki.yaml — SingleBinary mode, replication_factor 1
# (all in the shared values-base.yaml). singleBinary.persistence (chart default: enabled)
# binds against the gp3 StorageClass (Task 5's default-class annotation) -- no
# storageClassName override needed, same as kind relying on its own default `standard`
# StorageClass.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: loki
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://grafana.github.io/helm-charts
      chart: loki
      targetRevision: "7.0.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/loki/values-base.yaml
        valuesObject:
          singleBinary:
            nodeSelector:
              openlex.dev/workload: observability
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
            resources:
              requests: { cpu: 50m, memory: 128Mi }
              limits: { cpu: 200m, memory: 384Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
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

- [ ] **Step 2: Write the Promtail Application**

Read `infra/argocd/apps/kind/app-promtail.yaml` first:

```yaml
# infra/argocd/apps/eks-demo/app-promtail.yaml
#
# Identical to infra/argocd/apps/kind/app-promtail.yaml — DaemonSet, deliberately no
# nodeSelector (must run on both node groups to ship openlex-api/worker's own pod logs too,
# not just observability-node components), three-entry toleration list (control-plane taint +
# master taint + the observability taint) so nothing gets silently dropped by Helm's
# array-replace-not-merge values semantics -- same reasoning as kind's own file.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: promtail
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://grafana.github.io/helm-charts
      chart: promtail
      targetRevision: "6.17.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/promtail/values-base.yaml
        valuesObject:
          tolerations:
            - key: node-role.kubernetes.io/master
              operator: Exists
              effect: NoSchedule
            - key: node-role.kubernetes.io/control-plane
              operator: Exists
              effect: NoSchedule
            - key: openlex.dev/workload
              operator: Equal
              value: observability
              effect: NoSchedule
          resources:
            requests: { cpu: 25m, memory: 64Mi }
            limits: { cpu: 100m, memory: 128Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
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

- [ ] **Step 3: Validate**

```bash
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-loki.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-loki.yaml)
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-promtail.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-promtail.yaml)
```

Expected: same pattern as Task 6 Step 5 — only header comment/`project`/`targetRevision`
differ.

```bash
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['infra/argocd/apps/eks-demo/app-loki.yaml','infra/argocd/apps/eks-demo/app-promtail.yaml']]" && echo OK
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-loki.yaml infra/argocd/apps/eks-demo/app-promtail.yaml
git commit -m "Mirror kind's Loki/Promtail onto eks-demo (7.6 revised)"
```

---

### Task 8: Observability — kube-prometheus-stack + dashboards (mirrors kind) (7.6 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml`,
  `infra/argocd/apps/eks-demo/app-observability-dashboards.yaml`
- Modify: `infra/argocd/projects/appproject-eks-demo.yaml`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability` taint/label (Task 4), Tempo's
  `metricsGenerator.remoteWriteUrl` (Task 6, already hardcoded in the shared
  `tempo/values-base.yaml` to `kube-prometheus-stack-prometheus.observability.svc.cluster.local`
  — this Service name is what this task's Application name (`kube-prometheus-stack`) produces
  via the chart's default fullname).
- Produces: a `kube-prometheus-stack-grafana` Service (port 80) — consumed by Task 10's
  Ingress. A `kube-prometheus-stack-prometheus` Service (port 9090) and
  `kube-prometheus-stack-alertmanager` Service (port 9093) — consumed by Task 10's
  port-forward script.

- [ ] **Step 1: Add the prometheus-community chart repo to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://prometheus-community.github.io/helm-charts
```

- [ ] **Step 2: Write the kube-prometheus-stack Application**

Read `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml` first (the largest of the mirrored
files — same reasoning applies: only `project`, `targetRevision`, and the Grafana
`additionalDataSources` block differ, since eks-demo's Tempo/Jaeger/Loki Services live at the
same in-cluster DNS names as kind's, just resolved against this cluster instead):

```yaml
# infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml
#
# Identical to infra/argocd/apps/kind/app-kube-prometheus-stack.yaml, including the shared
# values-base.yaml's additionalPrometheusRulesMap (the five symptom-based alerts) and
# Grafana's dashboard sidecar config -- both apply to eks-demo automatically once this
# Application syncs, no separate wiring needed. additionalDataSources' URLs are unchanged from
# kind's: Tempo/Jaeger/Loki resolve at the same in-cluster Service DNS names here as they do
# on kind (Tasks 6/7 gave eks-demo its own tempo/jaeger/loki Services in the same
# `observability` namespace).
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kube-prometheus-stack
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://prometheus-community.github.io/helm-charts
      chart: kube-prometheus-stack
      targetRevision: "87.15.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/kube-prometheus-stack/values-base.yaml
        valuesObject:
          prometheusOperator:
            nodeSelector:
              openlex.dev/workload: observability
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
          prometheus:
            prometheusSpec:
              retention: 6h
              nodeSelector:
                openlex.dev/workload: observability
              tolerations:
                - key: openlex.dev/workload
                  operator: Equal
                  value: observability
                  effect: NoSchedule
              resources:
                requests: { cpu: 100m, memory: 400Mi }
                limits: { cpu: 500m, memory: 800Mi }
          alertmanager:
            alertmanagerSpec:
              nodeSelector:
                openlex.dev/workload: observability
              tolerations:
                - key: openlex.dev/workload
                  operator: Equal
                  value: observability
                  effect: NoSchedule
              resources:
                requests: { cpu: 10m, memory: 32Mi }
                limits: { cpu: 100m, memory: 64Mi }
          grafana:
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
            additionalDataSources:
              - name: Tempo
                uid: tempo
                type: tempo
                access: proxy
                url: http://tempo.observability.svc.cluster.local:3200
                isDefault: false
                jsonData:
                  serviceMap:
                    datasourceUid: prometheus
              - name: Jaeger
                uid: jaeger
                type: jaeger
                access: proxy
                url: http://jaeger.observability.svc.cluster.local:16686
                isDefault: false
              - name: Loki
                uid: loki
                type: loki
                access: proxy
                url: http://loki.observability.svc.cluster.local:3100
                isDefault: false
          kube-state-metrics:
            nodeSelector:
              openlex.dev/workload: observability
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
            resources:
              requests: { cpu: 10m, memory: 32Mi }
              limits: { cpu: 50m, memory: 64Mi }
          prometheus-node-exporter:
            # Blanket toleration (not scoped to the observability taint alone) so this
            # DaemonSet also schedules on the control-plane and apps node groups -- same
            # reasoning as kind's own file (a scoped-only toleration here previously caused a
            # live bug on kind where node-exporter silently missed the control-plane node,
            # since Helm values arrays replace rather than merge with the chart default).
            tolerations:
              - effect: NoSchedule
                operator: Exists
            resources:
              requests: { cpu: 10m, memory: 24Mi }
              limits: { cpu: 50m, memory: 48Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

- [ ] **Step 3: Write the observability-dashboards Application**

Read `infra/argocd/apps/kind/app-observability-dashboards.yaml` first — this one needs zero
content changes at all beyond `project`/`targetRevision`, since
`infra/monitoring/grafana/dashboards/` is already environment-agnostic PromQL/LogQL/TraceQL
JSON, consumed via Kustomize (not Helm), so there's no `$values` multi-source pattern to adapt:

```yaml
# infra/argocd/apps/eks-demo/app-observability-dashboards.yaml
#
# Identical to infra/argocd/apps/kind/app-observability-dashboards.yaml. The dashboard JSON
# itself (infra/monitoring/grafana/dashboards/) needs zero eks-demo-specific changes -- it's
# PromQL/LogQL/TraceQL querying Prometheus/Loki/Tempo by Service DNS name, and eks-demo's
# Tempo/Jaeger/Loki/Prometheus resolve at those same names (Tasks 6/7/8's Applications all
# live in the same `observability` namespace kind uses). This is what resolves the original
# 7.6 draft's open question about needing parallel CloudWatch-flavored dashboards -- moot,
# since eks-demo never queries CloudWatch at all under this revised design.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: observability-dashboards
  namespace: argocd
spec:
  project: openlex-eks-demo
  source:
    repoURL: https://github.com/rozdolsky33/OpenLex.git
    targetRevision: main
    path: infra/monitoring/grafana/dashboards
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

- [ ] **Step 4: Validate**

```bash
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-kube-prometheus-stack.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml)
diff infra/argocd/apps/kind/app-observability-dashboards.yaml infra/argocd/apps/eks-demo/app-observability-dashboards.yaml
```

Expected: only header comment/`project`/`targetRevision` differ in both files — confirm no
other line drifted (this is the largest mirrored file; a missed line here is easy to miss by
eye alone, which is why this diff check matters more here than anywhere else in Task 6-8).

```bash
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml','infra/argocd/apps/eks-demo/app-observability-dashboards.yaml']]" && echo OK
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml infra/argocd/apps/eks-demo/app-observability-dashboards.yaml infra/argocd/projects/appproject-eks-demo.yaml
git commit -m "Mirror kind's kube-prometheus-stack + dashboards onto eks-demo (7.6 revised)"
```

---

### Task 9: Observability — postgres-exporter retargeted at RDS (7.6 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-postgres-exporter.yaml`

**Interfaces:**
- Consumes: `POSTGRES_EXPORTER_DSN` key in the `openlex-secrets` k8s Secret (Task 1's
  `aws_secretsmanager_secret_version.app`, flowing through `externalsecret-openlex.yaml`'s
  `dataFrom.extract`, confirmed automatic by Task 3), `openlex.dev/workload: apps` taint/label
  (Task 4), `prometheus-community.github.io/helm-charts` (already in the AppProject from Task
  8).
- Produces: nothing consumed by a later task — Prometheus (Task 8) discovers it automatically
  via its chart-native `serviceMonitor.enabled: true`, no manual wiring needed.

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-postgres-exporter.yaml`

- [ ] **Step 1: Write the Application**

Read `infra/argocd/apps/kind/app-postgres-exporter.yaml` first. The chart/values are identical
(the shared `infra/monitoring/postgres-exporter/values-base.yaml` already points
`config.datasourceSecret` at `openlex-secrets`/`POSTGRES_EXPORTER_DSN` — the same Secret name
and key on both environments, just sourced differently upstream: kind's `.env`-derived vs.
Task 1's RDS-derived). Only `project`/`targetRevision` and the `nodeSelector` differ from
kind's file — this one lives in the `openlex` namespace, on the `apps` node group, not
`observability`, matching kind's own placement rationale (it reads the same
`openlex`-namespace Secret the app itself uses):

```yaml
# infra/argocd/apps/eks-demo/app-postgres-exporter.yaml
#
# Identical to infra/argocd/apps/kind/app-postgres-exporter.yaml. config.datasourceSecret
# (in the shared values-base.yaml) points at the same openlex-secrets/POSTGRES_EXPORTER_DSN
# key kind uses -- here it resolves to RDS (Task 1's rds.tf writes that key), not the
# in-cluster StatefulSet kind's key resolves to. Deliberately not in the `observability`
# namespace (same as kind): Prometheus already watches ServiceMonitors across every namespace
# (serviceMonitorSelectorNilUsesHelmValues: false, in the shared kube-prometheus-stack
# values-base.yaml), so this doesn't need to live in `observability` to be scraped, and
# staying in `openlex` avoids duplicating DB credentials into a second namespace.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: postgres-exporter
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://prometheus-community.github.io/helm-charts
      chart: prometheus-postgres-exporter
      targetRevision: "8.1.1"
      helm:
        valueFiles:
          - $values/infra/monitoring/postgres-exporter/values-base.yaml
        valuesObject:
          nodeSelector:
            openlex.dev/workload: apps
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
  destination:
    server: https://kubernetes.default.svc
    namespace: openlex
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 2: Validate**

```bash
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-postgres-exporter.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-postgres-exporter.yaml)
python3 -c "import yaml; yaml.safe_load(open('infra/argocd/apps/eks-demo/app-postgres-exporter.yaml'))" && echo OK
```

Expected: only header comment/`project`/`targetRevision` differ; `OK` printed.

- [ ] **Step 3: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-postgres-exporter.yaml
git commit -m "Mirror kind's postgres-exporter onto eks-demo, retargeted at RDS (7.6 revised)"
```

---

### Task 10: Ingress + oauth2-proxy for Grafana; port-forward script for Prometheus/Jaeger (7.9 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/{app-oauth2-proxy.yaml,
  externalsecret-oauth2-proxy.yaml,ingress-grafana.yaml}`,
  `scripts/eks-demo-observability-port-forward.sh`
- Modify: `infra/argocd/projects/appproject-eks-demo.yaml`, `infra/terraform/README.md`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability` taint/label (Task 4), the
  `kube-prometheus-stack-grafana` Service on port `80`, the
  `kube-prometheus-stack-prometheus` Service on port `9090`, the
  `kube-prometheus-stack-alertmanager` Service on port `9093` (all Task 8), the `jaeger`
  Service on port `16686` (Task 6), the `aws-secrets-manager` `ClusterSecretStore` (exists
  today, `infra/argocd/apps/eks-demo/secretstore-aws.yaml`).
- Produces: nothing consumed by a later task.

Per the design spec's revised 7.9: Grafana (plus ArgoCD's own existing login) gets real
internet-facing exposure. Prometheus and Jaeger get **no Ingress at all** — the port-forward
script is their only access path, mirroring `scripts/observability-port-forward.sh`'s existing
pattern for kind (not touching that file — a brand-new file, per 7.3's isolation discipline).

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
# Gates Grafana behind a single login (7.9 revised). GitHub OAuth chosen over a static
# htpasswd-style provider (spec's own open question, resolved here): oauth2-proxy's htpasswd
# support is a secondary/basic-auth fallback, not designed as a standalone primary provider,
# and GitHub OAuth is both the more realistic cloud-native pattern and a natural fit for a
# project that already lives on GitHub. Requires a GitHub OAuth App registered by hand
# (Settings -> Developer settings -> OAuth Apps -> New OAuth App, callback URL
# https://grafana.<DOMAIN>/oauth2/callback) — a manual one-time step in the same category as
# this project's other documented manual bootstrap steps (Route53 nameservers, Secrets Manager
# seed values). `<GITHUB_USERNAME>` restricts access to a single operator (replace with your
# own GitHub username) -- without it, any GitHub-authenticated user could log in. Client
# ID/secret/cookie secret come from externalsecret-oauth2-proxy.yaml, never committed here.
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
        nodeSelector:
          openlex.dev/workload: observability
        tolerations:
          - key: openlex.dev/workload
            operator: Equal
            value: observability
            effect: NoSchedule
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
# integration pattern. Targets kube-prometheus-stack-grafana (Task 8's bundled Grafana, not a
# standalone chart). Lives here, not infra/kubernetes/overlays/eks-demo/, for the same
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
                name: kube-prometheus-stack-grafana
                port:
                  number: 80
```

- [ ] **Step 5: Write the port-forward script for Prometheus/Jaeger (and Grafana/Alertmanager/ArgoCD for convenience)**

```bash
#!/usr/bin/env bash
# scripts/eks-demo-observability-port-forward.sh
#
# Prometheus and Jaeger have no built-in authentication and get no Ingress on eks-demo (see
# infra/argocd/apps/eks-demo/ingress-grafana.yaml's header comment and the design spec's
# revised 7.9) -- this is their only access path, mirroring
# scripts/observability-port-forward.sh's existing pattern for kind service-for-service. A
# brand-new file, not an extension of that script -- 7.3's isolation discipline means
# kind-only files never gain eks-demo-specific logic. Requires a kubeconfig context already
# pointed at the eks-demo cluster (`aws eks update-kubeconfig --name <cluster_name> --region
# <region>`, see infra/terraform/README.md's setup sequence) -- unlike kind's script, this
# doesn't assume it's the only cluster in your kubeconfig, so double-check your current
# context before running this.
set -euo pipefail

NAMESPACE="observability"
ARGOCD_NAMESPACE="argocd"

pids=()
cleanup() {
  echo
  echo "Stopping port-forwards..."
  for pid in "${pids[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-grafana 3000:80 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-prometheus 9090:9090 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-alertmanager 9093:9093 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/jaeger 16686:16686 &
pids+=($!)
kubectl port-forward -n "${ARGOCD_NAMESPACE}" svc/argocd-server 8080:443 &
pids+=($!)

echo "Grafana:      http://localhost:3000  (admin password: kubectl -n ${NAMESPACE} get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d)"
echo "Prometheus:   http://localhost:9090  (no auth -- port-forward only, see this script's header comment)"
echo "Alertmanager: http://localhost:9093"
echo "Jaeger:       http://localhost:16686  (no auth -- port-forward only, see this script's header comment)"
echo "ArgoCD:       https://localhost:8080  (admin password: kubectl -n ${ARGOCD_NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d, or the openlex/argocd-admin Secrets Manager password if already rotated)"
echo
echo "Press Ctrl-C to stop all port-forwards."
wait
```

```bash
chmod +x scripts/eks-demo-observability-port-forward.sh
```

- [ ] **Step 6: Update README.md's setup sequence**

Edit `infra/terraform/README.md`'s step 5 (from Task 1's version) to add, after the existing
`openlex/app`/`openlex/argocd-admin` bullets:

```
   Also create `openlex/oauth2-proxy` (JSON keys `client_id`, `client_secret`, `cookie_secret`)
   after registering a GitHub OAuth App (see
   `infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml`'s header comment for the exact steps).
```

- [ ] **Step 7: Cross-check the integration against oauth2-proxy's own docs**

`WebFetch` `https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview` and
`.../configuration/providers/github`. Confirm `upstreams: static://202` is the documented
auth-only-mode idiom, and that `provider: github` + `github-user` is the correct flag for
restricting to a single GitHub user. Record what was checked in the task report.

- [ ] **Step 8: Validate the new YAML/script**

```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/ingress-grafana.yaml')))" && echo OK
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml')))" && echo OK
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml')))" && echo OK
bash -n scripts/eks-demo-observability-port-forward.sh && echo "script syntax OK"
diff <(grep -vE "^#|^NAMESPACE=\"observability\"$" scripts/observability-port-forward.sh) <(grep -vE "^#|^NAMESPACE=\"observability\"$" scripts/eks-demo-observability-port-forward.sh) || true
```

Expected: `OK` printed 3 times, `script syntax OK`, and the final `diff` (informational, not a
strict pass/fail — `|| true` keeps it non-blocking) showing only the expected differences:
`cd "$(dirname...")/.."`'s removal (see the script's header comment on kubeconfig context),
the dropped OTLP/HTTP line (kind's script forwards the collector for `apps/web`'s browser
tracing; this plan's OTel Collector Application doesn't need the same local port-forward use
case documented here), and the updated echo text.

- [ ] **Step 9: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml infra/argocd/apps/eks-demo/ingress-grafana.yaml infra/argocd/projects/appproject-eks-demo.yaml infra/terraform/README.md scripts/eks-demo-observability-port-forward.sh
git commit -m "Add oauth2-proxy + Ingress for Grafana, port-forward script for Prometheus/Jaeger (7.9 revised)"
```

---

### Task 11: Static CDN — Terraform: S3 + CloudFront + ACM + GitHub OIDC role (7.8b)

**Files:**
- Create: `infra/terraform/static-site.tf`, `infra/terraform/iam_oidc_github_actions.tf`
- Modify: `infra/terraform/providers.tf`, `infra/terraform/versions.tf`,
  `infra/terraform/variables.tf`, `infra/terraform/outputs.tf`,
  `infra/kubernetes/overlays/eks-demo/ingress-api.yaml`

**Interfaces:**
- Consumes: `aws_route53_zone.demo` (`infra/terraform/route53.tf`, exists today),
  `var.domain_name` (exists today).
- Produces: `aws_s3_bucket.web`, `aws_cloudfront_distribution.web`,
  `aws_iam_role.github_actions_deploy_web.arn` — all three consumed by Task 12's
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
    cached_methods          = ["GET", "HEAD"]
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
# Lets .github/workflows/deploy-static.yml (Task 12) authenticate to AWS via GitHub's OIDC
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

### Task 12: Static CDN — apps/web production build + deploy-static.yml (7.8a + 7.8c)

**Files:**
- Create: `.github/workflows/deploy-static.yml`
- Modify: `infra/terraform/README.md`

**Interfaces:**
- Consumes: `apps/web`'s existing `npm run build` script (`package.json`, unchanged — already
  produces a real `dist/`, confirmed working during this plan's own research, see Step 1),
  Task 11's `web_bucket_name`/`cloudfront_distribution_id`/`github_actions_deploy_web_role_arn`
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

### Task 13: Terraform remote state (7.4)

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

**Spec coverage:** 7.1 → Tasks 1-2. 7.2 → Task 3. 7.3 → final-review check above (no dedicated
task, by design — no new code). 7.4 → Task 13. 7.5 → folded into Task 1's `aws_db_instance`
backup arguments. 7.6 (revised) → Tasks 6-9. 7.7 → Tasks 4-5. 7.8 → Tasks 11-12. 7.9 (revised)
→ Task 10.

**Placeholder scan:** no TBD/TODO markers; the `<PLACEHOLDER>` conventions used (`<DOMAIN>`,
`<GITHUB_USERNAME>`, `<*_ROLE_ARN>`) are the project's own established, real convention for
values a human hand-copies after `terraform apply` or hand-registers externally (e.g.
`<ACME_EMAIL>` in the existing `clusterissuer-letsencrypt.yaml`) — not unresolved plan gaps.

**Type/naming consistency:** `openlex.dev/workload` taint/label key and `observability`/`apps`
values are identical across Tasks 4, 5, 6, 7, 8, 9 and kind's existing files (verified by Task
5 Step 5's `grep` and Tasks 6-9's own `diff`-against-kind steps). `POSTGRES_EXPORTER_DSN` key
name is consistent between Task 1's `rds.tf` (which writes it) and the shared
`infra/monitoring/postgres-exporter/values-base.yaml` (which reads it via
`config.datasourceSecret.key` — unchanged by this plan, already correct). `DATABASE_URL` scheme
(`postgresql+asyncpg://`) is consistent between Task 1's `rds.tf` and Task 2's `job.yaml` (which
explicitly strips `+asyncpg` before handing the URL to `psql`). Service names Task 10's Ingress/
port-forward script depend on (`kube-prometheus-stack-grafana`, `kube-prometheus-stack-
prometheus`, `kube-prometheus-stack-alertmanager`, `jaeger`) all trace back to Task 6/8's
Application `metadata.name` values via each chart's default fullname templating — verified
against `scripts/observability-port-forward.sh`'s existing, live-proven service names for kind
(the same charts, same naming convention).

**No IAM/IRSA left over from the pre-revision design:** Tasks 6-9 (observability) contain zero
`.tf` files and zero `outputs.tf`/README hand-copy steps — confirmed by this plan's own File
Structure section listing only ArgoCD/Kubernetes YAML for those four tasks. This is a deliberate
consequence of the self-hosted design (see "Note on the 7.6/7.9 revision"), not an oversight.

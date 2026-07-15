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
  backup_window           = "06:00-07:00"         # low-traffic UTC hour
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

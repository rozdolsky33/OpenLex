variable "region" {
  description = "AWS region for the EKS demo cluster"
  type        = string
  default     = "us-east-1"
}

variable "domain_name" {
  description = <<-EOT
    Domain (or delegated subdomain, e.g. "demo.openlex-project.com") whose Route53 hosted zone
    Terraform creates. After apply, set this zone's nameservers (see `route53_name_servers`
    output) at your registrar. external-dns then manages the app./argocd. records dynamically.
  EOT
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "openlex-eks-demo"
}

variable "cluster_version" {
  description = "Kubernetes version — keep current to avoid EKS extended-support pricing (see docs/infrastructure/aws-eks-cost-estimate.md)"
  type        = string
  default     = "1.31"
}

variable "node_instance_type" {
  # t4g.large (not medium): the apps node group's pod capacity, not CPU/mem, is the constraint —
  # t4g.medium caps at ~17 max-pods (ENI-IP bound) and the platform+app exhaust it, stranding
  # reschedules (api surge pod) as Pending. t4g.large gives ~35 max-pods with no VPC-CNI prefix-
  # delegation complexity (which wouldn't create its addon reliably here). No GPU needed either way.
  description = "Instance type for the `apps` node group (t4g.large for pod capacity — see comment)"
  type        = string
  default     = "t4g.large"
}

variable "observability_node_instance_type" {
  description = "Instance type for the `observability` node group — larger than apps: kube-prometheus-stack + Tempo + Jaeger + Loki + Promtail + OTel Collector + ArgoCD together need more headroom"
  type        = string
  default     = "t4g.large"
}

variable "secrets_manager_path_prefix" {
  description = "Path prefix in AWS Secrets Manager that external-secrets is allowed to read"
  type        = string
  default     = "openlex"
}

variable "db_instance_class" {
  description = "RDS instance class — Graviton, matches this repo's cost-conscious node-type precedent"
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
  description = "Database name inside the RDS instance — matches local dev's docker-compose convention"
  type        = string
  default     = "openlex"
}

variable "db_username" {
  description = "Master username for the RDS instance — matches local dev's docker-compose convention"
  type        = string
  default     = "openlex"
}

variable "github_repository" {
  description = "GitHub \"owner/repo\" this project lives in — scopes the GitHub Actions OIDC trust policy"
  type        = string
  default     = "rozdolsky33/OpenLex"
}

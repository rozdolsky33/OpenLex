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
  description = "Single small Graviton instance type — no GPU needed (see ml/model_cards/bge-small-en-v1.5.md)"
  type        = string
  default     = "t4g.medium"
}

variable "node_desired_size" {
  description = "Node count — 1 is enough for this workload; see docs/infrastructure/aws-eks-cost-estimate.md"
  type        = number
  default     = 1
}

variable "secrets_manager_path_prefix" {
  description = "Path prefix in AWS Secrets Manager that external-secrets is allowed to read"
  type        = string
  default     = "openlex"
}

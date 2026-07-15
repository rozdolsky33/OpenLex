module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = false

  # Grant the IAM principal that runs `terraform apply` (the cluster creator) an
  # AmazonEKSClusterAdminPolicy access entry. Module v20 defaults this to false, which leaves
  # the creator unable to run kubectl against its own cluster (401 "must be logged in"). Kept
  # in Terraform (not a manual `aws eks create-access-entry`) so cluster access is codified,
  # not drift.
  enable_cluster_creator_admin_permissions = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets # no private subnets — see vpc.tf

  enable_irsa = true

  node_security_group_additional_rules = local.node_security_group_additional_rules

  # Both node groups use Graviton (t4g.*) instances — see var.node_instance_type /
  # var.observability_node_instance_type. The module defaults ami_type to AL2023_x86_64_STANDARD,
  # which EKS rejects for arm64 instances ("[t4g.medium] is not a valid instance type for
  # requested amiType AL2023_x86_64_STANDARD"). Set the arm64 AMI once here for all groups.
  eks_managed_node_group_defaults = {
    ami_type = "AL2023_ARM_64_STANDARD"
  }

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

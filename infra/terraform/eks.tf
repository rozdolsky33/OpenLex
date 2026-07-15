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

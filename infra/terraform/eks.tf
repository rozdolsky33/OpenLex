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
    default = {
      instance_types = [var.node_instance_type] # Graviton/arm64 — no GPU needed
      capacity_type  = "SPOT"

      min_size     = 1
      max_size     = 2
      desired_size = var.node_desired_size

      subnet_ids = module.vpc.public_subnets
      # ECR pull permissions for the node role come from the AmazonEC2ContainerRegistryReadOnly
      # policy the module attaches by default to every managed node group's IAM role.
    }
  }
}

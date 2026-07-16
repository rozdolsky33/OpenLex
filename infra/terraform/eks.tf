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

  # VPC CNI with ENI prefix delegation. t4g.medium's default max-pods is only ~17 (ENI-IP bound);
  # the platform + app exhaust it, so every reschedule (grafana roll, ingress-nginx roll, api
  # surge pod) gets stuck "Too many pods" / Pending. Prefix delegation raises max-pods to ~110.
  # Takes effect on newly-launched nodes — roll/replace the node groups after apply; on AL2023 EKS
  # computes the higher max-pods automatically from this addon config.
  cluster_addons = {
    vpc-cni = {
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "OVERWRITE"
      configuration_values = jsonencode({
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
  }

  # Both node groups use Graviton (t4g.*) instances — see var.node_instance_type /
  # var.observability_node_instance_type. The module defaults ami_type to AL2023_x86_64_STANDARD,
  # which EKS rejects for arm64 instances ("[t4g.medium] is not a valid instance type for
  # requested amiType AL2023_x86_64_STANDARD"). Set the arm64 AMI once here for all groups.
  eks_managed_node_group_defaults = {
    ami_type = "AL2023_ARM_64_STANDARD"

    # ENI prefix delegation (cluster_addons.vpc-cni above) raises the IPs available per node, but
    # on AL2023 the kubelet's --max-pods stays at the ENI-count default (~17 on t4g.medium) unless
    # set explicitly. Raise it via nodeadm so pods can actually use the extra IPs — 110 is the
    # standard prefix-delegation ceiling for <30-vCPU instances. New nodes only (roll after apply).
    cloudinit_pre_nodeadm = [{
      content_type = "application/node.eks.aws"
      content      = <<-EOT
        apiVersion: node.eks.aws/v1alpha1
        kind: NodeConfig
        spec:
          kubelet:
            config:
              maxPods: 110
      EOT
    }]
  }

  eks_managed_node_groups = {
    # Mirrors kind's dedicated-worker split (docs/infrastructure/kubernetes-topology.md):
    # ArgoCD + the full self-hosted observability stack (kube-prometheus-stack, Tempo, Jaeger,
    # Loki, Promtail, OTel Collector — see docs/superpowers/specs/
    # 2026-07-14-phase7-aws-rds-secrets-manager-design.md's 7.6, revised) get their own node
    # group, tainted so nothing else schedules there by accident.
    observability = {
      instance_types = [var.observability_node_instance_type] # larger than apps — see variables.tf
      # ON_DEMAND, not SPOT: this is a single node and everything observability-tainted
      # (grafana, oauth2-proxy, prometheus, loki, tempo, …) is pinned to it via nodeSelector, so a
      # spot reclaim takes the whole observability stack + grafana SSO down until a replacement
      # launches. One small on-demand node is worth the reliability. (apps stays SPOT — it has 2
      # nodes and the api runs multiple replicas.)
      capacity_type = "ON_DEMAND"

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

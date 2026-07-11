# Public-subnets-only, no NAT Gateway — see docs/infrastructure/aws-eks-cost-estimate.md:
# nodes get public IPs and reach the internet (ECR/Helm chart pulls, the Anthropic API, the NY
# Open Legislation API) directly through the IGW, gated by security_groups.tf's tightly scoped
# egress-only posture, instead of paying ~$32+/mo for a NAT Gateway.
data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = "10.42.0.0/16"

  azs             = slice(data.aws_availability_zones.available.names, 0, 2)
  public_subnets  = ["10.42.0.0/20", "10.42.16.0/20"]
  private_subnets = []

  map_public_ip_on_launch = true
  enable_nat_gateway      = false
  enable_dns_hostnames    = true
  enable_dns_support      = true

  public_subnet_tags = {
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

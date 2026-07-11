# The EKS module's default node security group already denies unsolicited inbound from the
# internet (only intra-VPC/cluster traffic + node-to-node is allowed by default) and permits
# all egress. The one deliberate opening below is required because ingress-nginx's Service is
# published via an *instance*-mode NLB (see app-ingress-nginx.yaml) — that NLB forwards client
# traffic straight to each node's NodePort, preserving the source IP, so it cannot be scoped to
# a single NLB-owned security group the way an ALB's would be. Scope is limited to the
# Kubernetes NodePort range, not all ports.
locals {
  node_security_group_additional_rules = {
    ingress_nodeport_from_internet = {
      description = "Allow the ingress-nginx instance-mode NLB to reach nodes' NodePort range"
      protocol    = "tcp"
      from_port   = 30000
      to_port     = 32767
      type        = "ingress"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }
}

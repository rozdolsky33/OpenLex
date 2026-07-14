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

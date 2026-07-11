# IRSA role for the `external-dns` Kubernetes ServiceAccount (namespace `external-dns`, name
# `external-dns` — must match infra/argocd/apps/eks-demo/app-external-dns.yaml's
# serviceAccount.name exactly, or the trust policy's `sub` condition never matches and the pod
# gets AccessDenied/no credentials). module.eks (enable_irsa = true) creates the cluster's OIDC
# provider; no separate provider resource needed here.
data "aws_iam_policy_document" "external_dns_trust" {
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
      values   = ["system:serviceaccount:external-dns:external-dns"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "external_dns" {
  name               = "${var.cluster_name}-external-dns"
  assume_role_policy = data.aws_iam_policy_document.external_dns_trust.json
}

data "aws_iam_policy_document" "external_dns_permissions" {
  statement {
    effect    = "Allow"
    actions   = ["route53:ChangeResourceRecordSets"]
    resources = [aws_route53_zone.demo.arn]
  }

  statement {
    effect    = "Allow"
    actions   = ["route53:ListHostedZones", "route53:ListResourceRecordSets"]
    resources = ["*"] # required by external-dns's discovery call; no ChangeResourceRecordSets outside the one zone above
  }
}

resource "aws_iam_role_policy" "external_dns" {
  name   = "external-dns-route53"
  role   = aws_iam_role.external_dns.id
  policy = data.aws_iam_policy_document.external_dns_permissions.json
}

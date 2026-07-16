# IRSA role for the Argo CD Image Updater ServiceAccount (namespace `argocd`, name
# `argocd-image-updater` — must match app-argocd-image-updater.yaml's serviceAccount.name).
# Lets the updater read image tags from ECR with no static credentials: its ecr-login.sh auth
# script (mounted by the chart) calls `aws ecr get-authorization-token`, authenticated by this
# role via IRSA. Read-only — the updater lists/inspects tags; it does not push. See
# infra/argocd/apps/eks-demo/app-argocd-image-updater.yaml and docs/infrastructure/eks-argocd-bootstrap.md.
data "aws_iam_policy_document" "image_updater_trust" {
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
      values   = ["system:serviceaccount:argocd:argocd-image-updater"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "image_updater" {
  name               = "${var.cluster_name}-image-updater"
  assume_role_policy = data.aws_iam_policy_document.image_updater_trust.json
}

data "aws_iam_policy_document" "image_updater_permissions" {
  # Account-level auth token (must be "*"; not per-repo).
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  # Read-only tag/metadata access, scoped to the openlex repositories.
  statement {
    sid    = "EcrRead"
    effect = "Allow"
    actions = [
      "ecr:DescribeImages",
      "ecr:ListImages",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [for r in aws_ecr_repository.this : r.arn]
  }
}

resource "aws_iam_role_policy" "image_updater" {
  name   = "image-updater-ecr-read"
  role   = aws_iam_role.image_updater.id
  policy = data.aws_iam_policy_document.image_updater_permissions.json
}

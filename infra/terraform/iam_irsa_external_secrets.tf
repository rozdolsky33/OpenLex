# IRSA role for the `external-secrets` ServiceAccount (namespace `external-secrets`, name
# `external-secrets` — must match app-external-secrets.yaml's serviceAccount.name and
# secretstore-aws.yaml's auth.jwt.serviceAccountRef exactly).
data "aws_iam_policy_document" "external_secrets_trust" {
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
      values   = ["system:serviceaccount:external-secrets:external-secrets"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "external_secrets" {
  name               = "${var.cluster_name}-external-secrets"
  assume_role_policy = data.aws_iam_policy_document.external_secrets_trust.json
}

# Scoped to the openlex/* path only — see variables.tf's secrets_manager_path_prefix.
data "aws_iam_policy_document" "external_secrets_permissions" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      "arn:aws:secretsmanager:${var.region}:*:secret:${var.secrets_manager_path_prefix}/*"
    ]
  }
}

resource "aws_iam_role_policy" "external_secrets" {
  name   = "external-secrets-secretsmanager"
  role   = aws_iam_role.external_secrets.id
  policy = data.aws_iam_policy_document.external_secrets_permissions.json
}

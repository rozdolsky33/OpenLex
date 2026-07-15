# infra/terraform/iam_oidc_github_actions_ecr.tf
#
# Lets .github/workflows/deploy.yml push the api/worker/web images to ECR via GitHub OIDC (no
# static AWS keys) — same OIDC provider as the deploy-web role, different permissions and branch
# scope. deploy.yml triggers on push to `develop` and does NOT use a GitHub Environment, so its
# OIDC token `sub` is `repo:<owner>/<repo>:ref:refs/heads/develop` (contrast the deploy-web role,
# which is scoped to `environment:production` because deploy-static.yml declares that environment).
# See docs/infrastructure/eks-argocd-bootstrap.md for how ECR fits the eks-demo image flow.
data "aws_iam_policy_document" "github_actions_ecr_push_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/develop"]
    }
  }
}

resource "aws_iam_role" "github_actions_ecr_push" {
  name               = "${var.cluster_name}-github-actions-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.github_actions_ecr_push_trust.json
}

data "aws_iam_policy_document" "github_actions_ecr_push_permissions" {
  # GetAuthorizationToken is an account-level action — it does not accept a repository ARN, so it
  # must be granted on "*" (this is the docker-login token, not push access to any image).
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Layer upload + manifest push (and the read actions buildx needs to skip already-present
  # layers), scoped to exactly the three openlex repositories.
  statement {
    sid    = "EcrPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for r in aws_ecr_repository.this : r.arn]
  }
}

resource "aws_iam_role_policy" "github_actions_ecr_push" {
  name   = "github-actions-ecr-push"
  role   = aws_iam_role.github_actions_ecr_push.id
  policy = data.aws_iam_policy_document.github_actions_ecr_push_permissions.json
}

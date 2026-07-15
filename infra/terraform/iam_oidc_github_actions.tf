# infra/terraform/iam_oidc_github_actions.tf
#
# Lets .github/workflows/deploy-static.yml (Task 7) authenticate to AWS via GitHub's OIDC
# federation -- no static AWS access keys in GitHub secrets, matching this project's "no
# static cloud credentials" precedent (IRSA everywhere else). Assumes no GitHub Actions OIDC
# provider already exists in this AWS account -- this project's own AWS account has never had
# any Terraform apply of any kind (see "Explicitly out of scope"), so this is safe to create
# fresh.
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

# Scoped to deploy-static.yml's `environment: production` job. A job that references a GitHub
# Environment gets an OIDC token whose `sub` is `repo:<owner>/<repo>:environment:<name>` — NOT
# `...:ref:refs/heads/main` — so the trust must match the environment form or AWS rejects the
# assume with "Not authorized to perform sts:AssumeRoleWithWebIdentity". To keep the "main only"
# guarantee, restrict the `production` environment's deployment branches to `main` in GitHub
# (Settings -> Environments -> production -> Deployment branches) — see
# docs/infrastructure/web-deploy.md.
data "aws_iam_policy_document" "github_actions_trust" {
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
      values   = ["repo:${var.github_repository}:environment:production"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy_web" {
  name               = "${var.cluster_name}-github-actions-deploy-web"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

data "aws_iam_policy_document" "github_actions_deploy_web_permissions" {
  statement {
    effect  = "Allow"
    actions = ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.web.arn,
      "${aws_s3_bucket.web.arn}/*",
    ]
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.web.arn]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy_web" {
  name   = "github-actions-deploy-web"
  role   = aws_iam_role.github_actions_deploy_web.id
  policy = data.aws_iam_policy_document.github_actions_deploy_web_permissions.json
}

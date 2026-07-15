#!/usr/bin/env bash
# scripts/eks/github-deploy-vars.sh
#
# Push the four GitHub Actions *variables* that .github/workflows/deploy-static.yml needs to
# deploy apps/web to S3 + CloudFront. Their values are all Terraform outputs of the eks-demo
# stack (infra/terraform), so this reads them straight from `terraform output` and sets them on
# the repo with `gh` — no hand-copying, no guessing which value goes where. Idempotent:
# `gh variable set` upserts, so rerun any time the infra is re-applied or a value changes.
#
# These are non-secret VARIABLES (bucket name, CloudFront id, role ARN, domain) — not secrets —
# so they're safe to store as Actions variables and to print here. The only real secrets in
# this pipeline are AWS creds, and there are none: deploy-static.yml authenticates via GitHub
# OIDC (infra/terraform/iam_oidc_github_actions.tf), assuming the role whose ARN is set below.
#
# Prereqs: `gh auth login` done; `terraform init` done in infra/terraform (state reachable);
# the eks-demo stack applied (so the outputs exist). See docs/infrastructure/web-deploy.md.
#
# NOTE ON NAMING: the role-ARN variable is OPENLEX_DEPLOY_WEB_ROLE_ARN, *not*
# GITHUB_ACTIONS_DEPLOY_WEB_ROLE_ARN — GitHub reserves the `GITHUB_` prefix for variable names
# and rejects it (HTTP 422). Don't rename it back.
set -euo pipefail
# Resolve the script dir to an absolute path BEFORE the cd — otherwise the relative
# ${BASH_SOURCE[0]} would resolve against the new cwd on the source line below and break when
# the script is invoked from anywhere other than the repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."
# shellcheck source=scripts/_lib.sh
source "$SCRIPT_DIR/../_lib.sh"

TF_DIR="infra/terraform"
# Repo defaults to whatever `gh` infers from the cwd's git remote; override with REPO=owner/repo.
REPO="${REPO:-}"
gh_repo_flag=()
[ -n "$REPO" ] && gh_repo_flag=(--repo "$REPO")

banner "github-deploy-vars: set deploy-static Actions variables from terraform outputs"

command -v gh >/dev/null 2>&1 || die "gh (GitHub CLI) not found — install it and run 'gh auth login'."
command -v terraform >/dev/null 2>&1 || die "terraform not found."
# Test real API access, not `gh auth status` — the latter exits non-zero if *any* account in
# the keyring is stale, even when the active account is fine.
gh api user --jq .login >/dev/null 2>&1 || die "gh can't reach the GitHub API — run 'gh auth login'."

step "Read values from terraform output ($TF_DIR)"
tf_out() { # tf_out <output-name>
  terraform -chdir="$TF_DIR" output -raw "$1" 2>/dev/null \
    || die "terraform output '$1' failed — is the eks-demo stack applied and 'terraform init' done in $TF_DIR? (see docs/infrastructure/web-deploy.md)"
}
# domain_name is a plain input var — prefer its terraform output, but fall back to reading
# terraform.tfvars directly so this works even before the next `terraform apply` publishes the
# (newly added) output. The other three are computed resource attributes, output-only.
DOMAIN="$(terraform -chdir="$TF_DIR" output -raw domain_name 2>/dev/null \
  || sed -n 's/^[[:space:]]*domain_name[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$TF_DIR/terraform.tfvars")"
[ -n "$DOMAIN" ] || die "could not resolve domain_name from terraform output or $TF_DIR/terraform.tfvars"
BUCKET="$(tf_out web_bucket_name)"
CF_ID="$(tf_out cloudfront_distribution_id)"
ROLE_ARN="$(tf_out github_actions_deploy_web_role_arn)"
info "OPENLEX_DOMAIN                     = $DOMAIN"
info "OPENLEX_WEB_BUCKET                 = $BUCKET"
info "OPENLEX_CLOUDFRONT_DISTRIBUTION_ID = $CF_ID"
info "OPENLEX_DEPLOY_WEB_ROLE_ARN        = $ROLE_ARN"

step "Set the four repo variables (upsert)"
set_var() { # set_var <NAME> <VALUE>
  gh variable set "$1" "${gh_repo_flag[@]}" --body "$2"
  ok "$1"
}
set_var OPENLEX_DOMAIN "$DOMAIN"
set_var OPENLEX_WEB_BUCKET "$BUCKET"
set_var OPENLEX_CLOUDFRONT_DISTRIBUTION_ID "$CF_ID"
set_var OPENLEX_DEPLOY_WEB_ROLE_ARN "$ROLE_ARN"

done_banner "deploy-static variables are set. Push apps/web changes to main to trigger a deploy."

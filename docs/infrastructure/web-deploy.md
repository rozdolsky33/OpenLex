# Web deploy: apps/web → S3 + CloudFront

How the production build of `apps/web` (the Vite/React SPA) gets published, and the one-time
setup a fresh account needs so the pipeline runs without anyone hand-copying values.

On EKS, `app.<domain>` is **not** served by the cluster — it's a static SPA on **S3 + CloudFront**
(only `api.<domain>` stays on ingress-nginx). See `infra/terraform/static-site.tf`.

## The pipeline (steady state)

`.github/workflows/deploy-static.yml` runs on **push to `main`** touching `apps/web/**`:

```
push to main (apps/web/**) ─► GitHub Actions
   1. npm ci && npm run build       (VITE_API_BASE_URL = https://api.<OPENLEX_DOMAIN>)
   2. configure-aws-credentials      (GitHub OIDC → assume OPENLEX_DEPLOY_WEB_ROLE_ARN, no static keys)
   3. aws s3 sync dist/ s3://OPENLEX_WEB_BUCKET --delete
   4. aws cloudfront create-invalidation --distribution-id OPENLEX_CLOUDFRONT_DISTRIBUTION_ID
```

There is **no manual upload** — pushing web changes to `main` is the deploy. The workflow has no
`workflow_dispatch`, so it can't be hand-triggered from the Actions UI (add one if you want that).

## What it depends on (the four Actions *variables*)

The workflow reads four repo-level **variables** (not secrets — all non-sensitive). Every value is
a Terraform output of the eks-demo stack, so there's a single source of truth:

| GitHub Actions variable | Value source (`terraform output …`) | What it is |
|---|---|---|
| `OPENLEX_DOMAIN` | `domain_name` (from `terraform.tfvars`) | base domain, e.g. `openlex.arwest.dev` |
| `OPENLEX_WEB_BUCKET` | `web_bucket_name` | S3 bucket the SPA syncs to |
| `OPENLEX_CLOUDFRONT_DISTRIBUTION_ID` | `cloudfront_distribution_id` | distribution to invalidate |
| `OPENLEX_DEPLOY_WEB_ROLE_ARN` | `github_actions_deploy_web_role_arn` | IAM role Actions assumes via OIDC |

> **Naming gotcha (do not "fix"):** the role variable is `OPENLEX_DEPLOY_WEB_ROLE_ARN`, not
> `GITHUB_ACTIONS_DEPLOY_WEB_ROLE_ARN`. GitHub **reserves the `GITHUB_` prefix** for Actions
> variable names and rejects it with HTTP 422. If `configure-aws-credentials` ever logs
> *"Credentials could not be loaded from any providers,"* the first thing to check is that this
> variable exists and is non-empty — an unset role ARN produces exactly that error.

## One-time setup (fresh account, in order)

1. **Apply the Terraform** (`infra/terraform`) — creates the S3 bucket, CloudFront distribution,
   ACM cert, OIDC provider, and deploy role. The AWS side of OIDC (provider + role trust scoped
   to `repo:<owner>/<repo>:ref:refs/heads/main`) is entirely in `iam_oidc_github_actions.tf`.

   ⚠️ **The apply blocks on DNS.** `aws_acm_certificate_validation.web` waits for the
   `app.<domain>` cert to be **ISSUED**, which requires the subdomain **delegation** to be live
   (see [dns-subdomain-delegation.md](./dns-subdomain-delegation.md)). Until then, `terraform
   apply` cannot finish, so **`aws_cloudfront_distribution.web` and the `cloudfront_distribution_id`
   output don't exist yet.** Get the delegation working first; then the apply completes and the
   outputs are real.

2. **Set the four GitHub variables** — don't hand-copy them. Run the automation, which reads the
   Terraform outputs and upserts the variables (idempotent, safe to rerun):

   ```bash
   scripts/eks/github-deploy-vars.sh
   # REPO=owner/repo scripts/eks/github-deploy-vars.sh   # if gh can't infer the repo
   ```

   Requires `gh auth login` and `terraform init` done in `infra/terraform`. Because it reads
   `cloudfront_distribution_id` from Terraform, **run it *after* step 1's apply completes** — that
   guarantees the distribution id is the real, Terraform-managed one, not a stale value.

3. **Push a web change to `main`** (or merge `develop` → `main`) to trigger the first real deploy.
   To populate the bucket immediately without waiting, you can also seed it by hand with the same
   command the workflow uses:
   ```bash
   (cd apps/web && npm ci && VITE_API_BASE_URL="https://api.$(terraform -chdir=../../infra/terraform output -raw domain_name)" npm run build)
   aws s3 sync apps/web/dist/ "s3://$(terraform -chdir=infra/terraform output -raw web_bucket_name)" --delete
   ```

## Why is the site not up yet? (troubleshooting)

| Symptom | Cause | Fix |
|---|---|---|
| Actions: *"Credentials could not be loaded from any providers"* | `OPENLEX_DEPLOY_WEB_ROLE_ARN` unset/empty (or was named with the forbidden `GITHUB_` prefix) | Run `scripts/eks/github-deploy-vars.sh`; confirm `gh variable list` shows all four |
| Actions: *"Not authorized to perform sts:AssumeRoleWithWebIdentity"* | The job uses `environment: production`, so the OIDC token's `sub` is `repo:<owner>/<repo>:environment:production`, not `...:ref:refs/heads/main`. If the IAM trust is scoped to the `ref` form, AWS rejects the assume. | Trust `sub` must be `repo:<owner>/<repo>:environment:production` (see `iam_oidc_github_actions.tf`). Restrict the `production` environment's deployment branches to `main` in GitHub to keep the "main only" guarantee. |
| `terraform output cloudfront_distribution_id` errors / missing | Apply stalled at `aws_acm_certificate_validation.web` — cert still `PENDING_VALIDATION` because the DNS delegation isn't live | Finish the delegation, let the cert reach `ISSUED`, re-run `terraform apply` |
| `https://app.<domain>` serves a cert/host error | CloudFront distribution has **0 aliases** until the cert is attached (same apply gate above) | Same as above; the raw `*.cloudfront.net` domain works in the meantime |
| A CloudFront distribution exists in AWS but **not in `terraform state list`** and has no tags | Orphan from an earlier partial/failed apply — Terraform will create a *different* managed one when the apply completes | Verify with `aws cloudfront list-tags-for-resource`; once the managed distribution exists, delete the orphan (`aws cloudfront` disable → delete) and re-run `scripts/eks/github-deploy-vars.sh` so the variable points at the managed id |

## Fully-Terraform alternative (optional)

The variable-setting in step 2 can be moved into Terraform itself with the
[`integrations/github`](https://registry.terraform.io/providers/integrations/github/latest) provider
and `github_actions_variable` resources sourced from the same outputs — then `terraform apply` sets
them and they can never drift. The tradeoff: Terraform then needs a GitHub token (`GITHUB_TOKEN`
env / a PAT) and you must `terraform import` the four variables if they already exist. The script
path above deliberately avoids adding that provider + credential; use whichever matches how much you
want in the apply.

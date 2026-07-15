# ADR-0007: GitOps image updates via Argo CD Image Updater (off develop's mainline)

## Status
Proposed

## Date
2026-07-15

## Context

The kind CD path was "CI writes image tags to git, ArgoCD reconciles": `deploy.yml` built
`ghcr.io/.../openlex-{api,worker,web}:<sha>` images on every push to `develop`, then committed a
`kustomize edit set image` tag bump back to `develop`'s `infra/kubernetes/overlays/kind/`
overlay as a `github-actions[bot]` commit (pushed with `GITHUB_TOKEN` so it wouldn't
re-trigger workflows). The kind `openlex` Application tracked `develop`.

That pattern is a legitimate GitOps approach, but the bot commit on `develop`'s mainline caused
two recurring problems, both observed live:

1. **Non-fast-forward races.** When a human PR merge advanced `develop` between the deploy job's
   checkout and its `git push HEAD:develop`, the push was rejected and the deploy failed.
   Mitigated with a rebase-retry loop (previous change), but the churn remained.
2. **Blocked `develop → main` promotions.** The bot deploy commit becomes `develop`'s tip, and
   `GITHUB_TOKEN`-pushed commits don't trigger CI — so the required `dependency-audit` /
   `secret-scan` checks never ran on the promotion PR's head, leaving it permanently `BLOCKED`.
   Every promotion needed a manual close/reopen to re-trigger checks.

The root cause is a single design choice: **machine-generated image commits live on the same
branch humans use as the source of truth.**

## Decision

Adopt **Argo CD Image Updater** and take image-tag commits off `develop`'s mainline:

- `deploy.yml` **only builds and pushes** the `:<sha>` images — the tag-bump/commit step is
  removed entirely.
- **Argo CD Image Updater** (`infra/argocd/apps/kind/app-argocd-image-updater.yaml`) watches
  GHCR, selects the **newest-built** image among `40-hex` sha tags, and **git-writes** the
  kustomize image tags to a dedicated **`gitops/kind`** branch, based on `develop`
  (`git-branch: develop:gitops/kind`) so it always carries the latest code plus the current
  image tags.
- The kind `openlex` Application tracks **`gitops/kind`** (not `develop`).

`develop` therefore stays **code-only** — human commits, no machine image commits — so
`develop → main` promotions are always clean, and there is no push race.

Image Updater v1.2.x is **CRD-based**: it acts on `ImageUpdater` custom resources, not directly
on the Application annotations. So an `ImageUpdater` CR
(`infra/argocd/apps/kind/imageupdater-openlex.yaml`) selects the openlex app with
`useAnnotations: true`, which tells the controller to read the image config from that app's
annotations — the config still lives on the Application. The `openlex-kind` AppProject's
`sourceRepos` must also allow the `argoproj.github.io/argo-helm` chart repo.

Credentials (kind-only, from `.env` via `scripts/kind/secrets-bootstrap.sh`): a `repo`-scoped
`GIT_WRITE_TOKEN` for the git write-back (`argocd-image-updater-git` Secret) and GHCR read creds
(`ghcr` Secret). The `gitops/kind` branch is initialized once with
`scripts/kind/gitops-branch-init.sh`.

## Consequences

- **Easier:** `develop` mainline is human-only; promotions never snag on a bot-commit head; no
  non-fast-forward race; image automation is a standard, portfolio-credible GitOps pattern.
- **Harder / new moving parts:** a controller to run, two new Secrets, a `GIT_WRITE_TOKEN` PAT
  the operator must supply, and the `gitops/kind` branch to initialize. The deployed image
  state now lives on `gitops/kind`, not `develop` — read that branch (or the ArgoCD UI) to see
  what's deployed.
- **Scope:** kind only. `eks-demo` is unchanged (design-only; it can adopt the same pattern
  later). If `GIT_WRITE_TOKEN` is unset, the updater is inert and image tags can be bumped by
  hand — the stack still works.
- **Verification:** requires a live cluster — confirm the updater detects a new image and
  commits to `gitops/kind`, and that the `openlex` app syncs the new tag.

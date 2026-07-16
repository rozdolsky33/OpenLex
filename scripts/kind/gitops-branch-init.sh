#!/usr/bin/env bash
# One-time: create/reset the machine-managed gitops image-state branch for an environment.
#
#   scripts/kind/gitops-branch-init.sh kind       # gitops/kind  from origin/develop
#   scripts/kind/gitops-branch-init.sh eks-demo   # gitops/eks   from origin/main
#
# The openlex Application tracks this branch (not develop/main) -- it's the branch Argo CD Image
# Updater git-writes the current image tags into (see infra/argocd/apps/<env>/app-openlex.yaml).
# It must exist before the openlex app can sync on a fresh cluster; the updater keeps it up to
# date afterward (base branch code + image tags).
#
# Safe to re-run: fast-forwards the gitops branch to the latest base when the updater is idle. Do
# NOT run this while the updater has un-promoted image tags on the gitops branch that the base
# lacks -- it would reset them (re-derived on the next deploy anyway, but avoid the churn).
set -euo pipefail

ENV="${1:-kind}"
case "${ENV}" in
  kind)     BRANCH="gitops/kind"; BASE_REF="develop" ;;
  eks-demo) BRANCH="gitops/eks";  BASE_REF="main" ;;
  *) echo "Usage: $0 <kind|eks-demo>" >&2; exit 1 ;;
esac
BASE="origin/${BASE_REF}"

git fetch --quiet origin "${BASE_REF}"
echo "Pushing ${BASE} -> ${BRANCH}..."
git push origin "${BASE}:refs/heads/${BRANCH}"
echo "'${BRANCH}' branch is now at $(git rev-parse --short "${BASE}"). The openlex Application"
echo "tracks it; Argo CD Image Updater will git-write image tags onto it from here."

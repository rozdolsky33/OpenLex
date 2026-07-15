#!/usr/bin/env bash
# One-time: create/reset the `gitops/kind` branch from origin/develop.
#
# The kind openlex Application tracks `gitops/kind` (not develop) -- it's the machine-managed
# "deployed image state" branch that Argo CD Image Updater git-writes the current image tags
# into (see infra/argocd/apps/kind/app-openlex.yaml). It must exist before the openlex app can
# sync on a fresh cluster; the updater keeps it up to date afterward (base develop + image tags).
#
# Safe to re-run: fast-forwards gitops/kind to the latest develop when the updater is idle. Do
# NOT run this while the updater has un-promoted image tags on gitops/kind that develop lacks --
# it would reset them (they'd be re-derived on the next deploy anyway, but avoid the churn).
set -euo pipefail

BRANCH="gitops/kind"
BASE="origin/develop"

git fetch --quiet origin develop
echo "Pushing ${BASE} -> ${BRANCH}..."
git push origin "${BASE}:refs/heads/${BRANCH}"
echo "'${BRANCH}' branch is now at $(git rev-parse --short "${BASE}"). The openlex Application"
echo "tracks it; Argo CD Image Updater will git-write image tags onto it from here."

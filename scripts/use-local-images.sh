#!/usr/bin/env bash
# Local-only counterpart to deploy.yml's GHCR tag bump: after scripts/kind-load-images.sh
# loads fresh :kind-local images into the kind cluster's containerd store, this points the
# overlay's committed images: block at those tags instead of whatever ghcr.io/...:<sha> the
# last real deploy set -- otherwise ArgoCD/kubectl would keep pulling the old GHCR image, not
# the freshly-loaded local one.
#
# Deliberately NOT committed or pushed -- this is an uncommitted, working-tree-only edit. Once
# you're done iterating, `git checkout -- infra/kubernetes/overlays/kind/kustomization.yaml`
# (or a fresh `git pull`) restores the real GHCR-tag state. Never run this as part of any CI
# workflow.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v kustomize >/dev/null 2>&1; then
  echo "kustomize CLI not found — install it first (e.g. \`brew install kustomize\`)." >&2
  exit 1
fi

cd infra/kubernetes/overlays/kind
kustomize edit set image \
  openlex-api=openlex-api:kind-local \
  openlex-worker=openlex-worker:kind-local \
  openlex-web=openlex-web:kind-local

echo "overlays/kind/kustomization.yaml now points at :kind-local images (uncommitted)."
echo "Apply with: kubectl apply -k infra/kubernetes/overlays/kind"
echo "Revert with: git checkout -- infra/kubernetes/overlays/kind/kustomization.yaml"

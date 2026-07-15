#!/usr/bin/env bash
# Manual, idempotent GHCR pull-secret bootstrap for the kind cluster -- same category of
# exception as scripts/kind/secrets-bootstrap.sh (kind has no IRSA/External Secrets Operator to
# automate this). Creates a docker-registry Secret so kubelet can pull the private
# ghcr.io/<owner>/openlex-{api,worker,web} images deploy.yml publishes. Not committed anywhere;
# not managed by ArgoCD. Safe to re-run after rotating GHCR_PAT in .env.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

NAMESPACE="openlex"

if [ ! -f .env ]; then
  echo "No .env found — run scripts/compose/bootstrap.sh first (or copy .env.example to .env and fill it in)." >&2
  exit 1
fi

GHCR_USERNAME="$(grep '^GHCR_USERNAME=' .env | cut -d= -f2-)"
GHCR_PAT="$(grep '^GHCR_PAT=' .env | cut -d= -f2-)"

if [ -z "$GHCR_USERNAME" ] || [ -z "$GHCR_PAT" ]; then
  echo "GHCR_USERNAME and/or GHCR_PAT are empty in .env — set both (a GitHub personal access token with 'read:packages' scope) before running this." >&2
  exit 1
fi

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret docker-registry ghcr-pull-secret \
  --namespace "${NAMESPACE}" \
  --docker-server=ghcr.io \
  --docker-username="${GHCR_USERNAME}" \
  --docker-password="${GHCR_PAT}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "ghcr-pull-secret created/updated in namespace '${NAMESPACE}' from .env."

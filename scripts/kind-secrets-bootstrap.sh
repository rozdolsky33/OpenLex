#!/usr/bin/env bash
# The one deliberate manual exception to GitOps in kind: External Secrets Operator (used on the
# EKS demo) needs IRSA, which a local kind cluster doesn't have. This creates a plain k8s
# Secret from the local .env instead — same Secret name (`openlex-secrets`) that
# infra/kubernetes/base/{api,worker} reference via envFrom, so the app manifests don't need to
# know which mechanism populated it. Not committed anywhere; not managed by ArgoCD. Idempotent
# (safe to re-run after editing .env).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAMESPACE="openlex"

if [ ! -f .env ]; then
  echo "No .env found — run scripts/bootstrap.sh first (or copy .env.example to .env and fill it in)." >&2
  exit 1
fi

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic openlex-secrets \
  --namespace "${NAMESPACE}" \
  --from-env-file=.env \
  --dry-run=client -o yaml | kubectl apply -f -

echo "openlex-secrets created/updated in namespace '${NAMESPACE}' from .env."

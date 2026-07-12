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

# .env's DATABASE_URL points at `db` (docker-compose's Postgres service name) — in kind, the
# Postgres Service is named `postgres` (infra/kubernetes/base/postgres/service.yaml). Rewrite
# just the host on the way into the Secret so the same .env works for both without editing it
# by hand; discovered while bootstrapping observability Phase 1 (api's /healthz reported
# `db: false` until this was fixed).
kubectl create secret generic openlex-secrets \
  --namespace "${NAMESPACE}" \
  --from-env-file=<(sed -E 's#(DATABASE_URL=.*@)db(:[0-9]+/)#\1postgres\2#' .env) \
  --dry-run=client -o yaml | kubectl apply -f -

echo "openlex-secrets created/updated in namespace '${NAMESPACE}' from .env."

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
#
# Also derive POSTGRES_EXPORTER_DSN: prometheus-postgres-exporter's `config.datasourceSecret`
# (infra/monitoring/postgres-exporter/values-base.yaml) expects a plain libpq DSN
# (`postgresql://...`), but DATABASE_URL is `postgresql+asyncpg://...` (SQLAlchemy's async
# driver scheme, needed by apps/api and apps/worker) — the `+asyncpg` suffix isn't a scheme
# libpq/the exporter's Go driver understands. Rather than duplicating credentials into a
# second Secret, derive one extra key here from the same host-rewritten DATABASE_URL, with
# `+asyncpg` stripped and `sslmode=disable` appended (Postgres itself has no TLS configured on
# kind) — same Secret, same source of truth, one additional key.
# `kubectl create secret --from-env-file` refuses to be combined with `--from-literal` (kubectl
# itself: "from-env-file cannot be combined with from-file or from-literal"), so the derived
# key is appended as one more line to the same host-rewritten env stream instead of passed
# separately.
POSTGRES_EXPORTER_DSN="$(
  sed -E 's#(DATABASE_URL=.*@)db(:[0-9]+/)#\1postgres\2#' .env \
    | grep '^DATABASE_URL=' \
    | sed -E 's/^DATABASE_URL=//; s#\+asyncpg##'
)?sslmode=disable"

kubectl create secret generic openlex-secrets \
  --namespace "${NAMESPACE}" \
  --from-env-file=<(
    sed -E 's#(DATABASE_URL=.*@)db(:[0-9]+/)#\1postgres\2#' .env
    echo "POSTGRES_EXPORTER_DSN=${POSTGRES_EXPORTER_DSN}"
  ) \
  --dry-run=client -o yaml | kubectl apply -f -

echo "openlex-secrets created/updated in namespace '${NAMESPACE}' from .env."

#!/usr/bin/env bash
# The one deliberate manual exception to GitOps in kind: External Secrets Operator (used on the
# EKS demo) needs IRSA, which a local kind cluster doesn't have. This creates a plain k8s
# Secret from the local .env instead — same Secret name (`openlex-secrets`) that
# infra/kubernetes/base/{api,worker} reference via envFrom, so the app manifests don't need to
# know which mechanism populated it. Not committed anywhere; not managed by ArgoCD. Idempotent
# (safe to re-run after editing .env).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

NAMESPACE="openlex"

if [ ! -f .env ]; then
  echo "No .env found — run scripts/compose/bootstrap.sh first (or copy .env.example to .env and fill it in)." >&2
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

# Build the env stream in a temp file rather than a process substitution glued to
# `--from-env-file=<(...)`: macOS's system bash (3.2) can't parse process substitution in the
# mid-word `=<(...)` position and fails with "bad substitution: no closing `)'". A temp file is
# portable across bash versions and equivalent for --from-env-file.
ENV_FILE="$(mktemp)"
trap 'rm -f "${ENV_FILE}"' EXIT
{
  sed -E 's#(DATABASE_URL=.*@)db(:[0-9]+/)#\1postgres\2#' .env
  # Leading \n: if .env has no trailing newline, this derived key would otherwise be
  # concatenated onto .env's last line (kubectl would then read GHCR_PAT=<pat>POSTGRES_...
  # as one key and POSTGRES_EXPORTER_DSN would never exist -- observed live on a fresh
  # cluster). The extra blank line when .env *does* end in a newline is ignored by
  # --from-env-file.
  printf '\nPOSTGRES_EXPORTER_DSN=%s\n' "${POSTGRES_EXPORTER_DSN}"
} >"${ENV_FILE}"

kubectl create secret generic openlex-secrets \
  --namespace "${NAMESPACE}" \
  --from-env-file="${ENV_FILE}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "openlex-secrets created/updated in namespace '${NAMESPACE}' from .env."

# Stable Grafana admin password. kube-prometheus-stack's Grafana otherwise mints a new random
# admin-password on every ArgoCD sync (Helm randAlphaNum), which drifts out of sync with the
# running pod and breaks `admin` login. Pin it via a fixed Secret in the observability
# namespace, referenced by the kube-prometheus-stack values' grafana.admin.existingSecret.
# (Anonymous access still works without any login; this is only for editing / full admin.)
GRAFANA_ADMIN_PASSWORD="$(grep '^GRAFANA_ADMIN_PASSWORD=' .env | cut -d= -f2-)"
if [ -n "${GRAFANA_ADMIN_PASSWORD}" ]; then
  kubectl create namespace observability --dry-run=client -o yaml | kubectl apply -f -
  kubectl create secret generic grafana-admin \
    --namespace observability \
    --from-literal=admin-user=admin \
    --from-literal=admin-password="${GRAFANA_ADMIN_PASSWORD}" \
    --dry-run=client -o yaml | kubectl apply -f -
  echo "grafana-admin created/updated in namespace 'observability' from .env."
else
  echo "GRAFANA_ADMIN_PASSWORD not set in .env -- skipping grafana-admin (Grafana keeps its" \
    "chart-generated random password; set it to pin the admin login)."
fi

# Argo CD Image Updater credentials in the argocd namespace (see
# infra/argocd/apps/kind/app-argocd-image-updater.yaml): a git write-back PAT so the updater can
# commit image tags to the gitops/kind branch, and GHCR read creds so it can list image tags.
# Only created if the tokens are set -- the updater is a kind-only convenience.
GIT_WRITE_TOKEN="$(grep '^GIT_WRITE_TOKEN=' .env | cut -d= -f2-)"
GHCR_USERNAME="$(grep '^GHCR_USERNAME=' .env | cut -d= -f2-)"
GHCR_PAT="$(grep '^GHCR_PAT=' .env | cut -d= -f2-)"
if [ -n "${GIT_WRITE_TOKEN}" ] && [ -n "${GHCR_USERNAME}" ] && [ -n "${GHCR_PAT}" ]; then
  kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
  # HTTPS git write-back creds: username + password(PAT with `repo` scope) -- keys per the
  # Argo CD Image Updater docs. Referenced by app-openlex.yaml's write-back-method annotation.
  kubectl create secret generic argocd-image-updater-git \
    --namespace argocd \
    --from-literal=username="${GHCR_USERNAME}" \
    --from-literal=password="${GIT_WRITE_TOKEN}" \
    --dry-run=client -o yaml | kubectl apply -f -
  # GHCR read creds (dockerconfig) so the updater can list openlex-* image tags. Referenced by
  # app-argocd-image-updater.yaml's registries[].credentials (pullsecret:argocd/ghcr).
  kubectl create secret docker-registry ghcr \
    --namespace argocd \
    --docker-server=ghcr.io \
    --docker-username="${GHCR_USERNAME}" \
    --docker-password="${GHCR_PAT}" \
    --dry-run=client -o yaml | kubectl apply -f -
  echo "argocd-image-updater-git + ghcr secrets created/updated in namespace 'argocd'."
else
  echo "GIT_WRITE_TOKEN / GHCR_* not all set in .env -- skipping Argo CD Image Updater secrets" \
    "(the updater won't be able to read GHCR or write the gitops/kind branch until they are)."
fi

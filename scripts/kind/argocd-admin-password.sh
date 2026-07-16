#!/usr/bin/env bash
# Pin the kind ArgoCD `admin` password to a stable value from .env (`ARGOCD_ADMIN`), so the
# local demo has a known, memorable credential instead of ArgoCD's chart-generated random
# `argocd-initial-admin-secret`. This mirrors the same pin-from-.env pattern
# scripts/kind/secrets-bootstrap.sh uses for Grafana (`GRAFANA_ADMIN_PASSWORD`), but ArgoCD
# gets its own dedicated key.
#
# Runs AFTER scripts/kind/argocd-bootstrap.sh (which installs ArgoCD with `helm --wait`, so
# deploy/argocd-server exists and the argocd-secret is present). Idempotent -- safe to re-run
# on every `kind-master.sh up`.
#
# Mechanism: ArgoCD stores the admin password as a bcrypt hash in the `argocd-secret` Secret
# under `admin.password` (+ `admin.passwordMtime`). We generate the hash with the `argocd`
# CLI *inside the argocd-server pod* (no host dependency on htpasswd / a local argocd binary),
# patch the Secret, and restart argocd-server so it reloads the new credential deterministically.
#
# kind-only: the eks-demo ArgoCD sits behind its own ingress/SSO access model, so this local
# convenience is intentionally not applied there.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

NAMESPACE="argocd"

if [ ! -f .env ]; then
  echo "No .env found -- run scripts/kind/secrets-bootstrap.sh first (or copy .env.example)." >&2
  exit 1
fi

ARGOCD_ADMIN="$(grep '^ARGOCD_ADMIN=' .env | cut -d= -f2-)"
if [ -z "${ARGOCD_ADMIN}" ]; then
  echo "ARGOCD_ADMIN not set in .env -- skipping ArgoCD admin password pin" \
    "(ArgoCD keeps its chart-generated random password in argocd-initial-admin-secret)."
  exit 0
fi

# argocd-server must be up (argocd-bootstrap.sh runs `helm --wait`, but be defensive if this
# script is invoked standalone).
kubectl -n "${NAMESPACE}" rollout status deploy/argocd-server --timeout=180s

# Generate the bcrypt hash with the argocd binary shipped in the server image -- a purely local
# command (no server login needed), so there's no host-tooling dependency.
HASH="$(kubectl -n "${NAMESPACE}" exec deploy/argocd-server -- \
  argocd account bcrypt --password "${ARGOCD_ADMIN}")"
if [ -z "${HASH}" ]; then
  echo "Failed to generate bcrypt hash from the argocd-server pod." >&2
  exit 1
fi

MTIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PATCH="$(printf '{"stringData":{"admin.password":"%s","admin.passwordMtime":"%s"}}' \
  "${HASH}" "${MTIME}")"
kubectl -n "${NAMESPACE}" patch secret argocd-secret --type merge -p "${PATCH}"

# Restart so argocd-server re-reads the credential deterministically (it also watches the
# Secret, but a restart removes any reload-timing ambiguity during a scripted bootstrap).
kubectl -n "${NAMESPACE}" rollout restart deploy/argocd-server
kubectl -n "${NAMESPACE}" rollout status deploy/argocd-server --timeout=180s

echo "ArgoCD admin password pinned to ARGOCD_ADMIN from .env (login: admin / <ARGOCD_ADMIN>)."

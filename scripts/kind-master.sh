#!/usr/bin/env bash
# Master orchestrator for the local kind environment.
#
#   scripts/kind-master.sh up     # full setup: cluster -> secrets -> ArgoCD -> wait -> ingest -> seed
#   scripts/kind-master.sh down   # tear the cluster down
#
# `up` chains the individual scripts under scripts/kind/ and scripts/seed/ and is idempotent
# (safe to re-run). Port-forwards are left to the caller (they block); the closing summary
# shows how to open them.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"
cd "${SCRIPT_DIR}/.."

NAMESPACE="openlex"
CMD="${1:-}"

up() {
  banner "kind-master: UP  (local Kubernetes + ArgoCD GitOps)"

  step "Pre-flight: .env present"
  [ -f .env ] || die "No .env found -- copy .env.example to .env and fill it in first."
  ok ".env found"

  step "Create kind cluster"
  scripts/kind/up.sh

  step "Bootstrap GHCR pull secret (private image pulls)"
  scripts/kind/ghcr-pull-secret-bootstrap.sh

  step "Bootstrap app secrets from .env -> openlex-secrets"
  scripts/kind/secrets-bootstrap.sh

  step "Ensure the gitops/kind image-state branch exists (openlex app tracks it)"
  if git ls-remote --exit-code --heads origin gitops/kind >/dev/null 2>&1; then
    ok "gitops/kind exists (Argo CD Image Updater keeps it current)"
  else
    info "creating gitops/kind from origin/develop..."
    scripts/kind/gitops-branch-init.sh
  fi

  step "Install ArgoCD + sync the app-of-apps"
  scripts/kind/argocd-bootstrap.sh kind

  step "Pin ArgoCD admin password from .env (ARGOCD_ADMIN)"
  scripts/kind/argocd-admin-password.sh

  step "Wait for ArgoCD to create + roll out the app pods"
  for deploy in openlex-api openlex-worker; do
    info "waiting for deploy/${deploy} to be created by ArgoCD..."
    until kubectl -n "${NAMESPACE}" get deploy "${deploy}" >/dev/null 2>&1; do sleep 5; done
    kubectl -n "${NAMESPACE}" rollout status "deploy/${deploy}" --timeout=600s
    ok "deploy/${deploy} rolled out"
  done

  step "Ingest corpus (statutes + cases)"
  scripts/seed/kind-ingest.sh
  ok "corpus ingested"

  step "Seed demo users"
  scripts/seed/kind-seed-demo-users.sh
  ok "demo users seeded"

  done_banner "kind cluster is up and populated."
  info "Open access in separate terminals (these block on kubectl port-forward):"
  info "  scripts/kind/app-port-forward.sh            # Web UI :5173, API :8000"
  info "  scripts/kind/observability-port-forward.sh  # Grafana :3000 (anon Editor), ArgoCD :8080, Jaeger :16686"
  info "Log in to the app with the DEMO_* credentials from your .env."
  info "ArgoCD logs in as: admin / ARGOCD_ADMIN (from your .env)."
  info "Re-run any port-forward after this script -- the pods just rolled, so older forwards are stale."
}

down() {
  banner "kind-master: DOWN  (delete the openlex kind cluster)"
  step "Delete kind cluster"
  scripts/kind/down.sh
  done_banner "kind cluster torn down."
}

case "${CMD}" in
  up)   up ;;
  down) down ;;
  *)    die "Usage: $(basename "$0") {up|down}" ;;
esac

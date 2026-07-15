#!/usr/bin/env bash
# Master bring-up for the local kind cluster: one command that gets you from nothing to a
# working, populated app on a real Kubernetes + ArgoCD GitOps stack. Chains the individual
# kind scripts in order:
#
#   1. guard: .env exists (secrets-bootstrap + ingest read it)
#   2. scripts/kind/up.sh                         -- create the `openlex` kind cluster
#   3. scripts/kind/ghcr-pull-secret-bootstrap.sh -- let the cluster pull private GHCR images
#   4. scripts/kind/secrets-bootstrap.sh          -- app secrets from .env -> openlex-secrets
#   5. scripts/kind/argocd-bootstrap.sh kind      -- install ArgoCD + app-of-apps root
#   6. wait for ArgoCD to create + roll out openlex-api / openlex-worker
#   7. scripts/seed/kind-ingest.sh                -- ingest statutes + cases into the cluster DB
#   8. scripts/seed/kind-seed-demo-users.sh       -- create the tier-gated demo logins
#
# Idempotent -- safe to re-run. Port-forwards are deliberately NOT started here (they block);
# the final message shows how to open them.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

NAMESPACE="openlex"

# --- 1. .env guard ---
if [ ! -f .env ]; then
  echo "ERROR: no .env found -- copy .env.example to .env and fill it in first." >&2
  exit 1
fi

# --- 2-5. cluster + platform bring-up ---
echo "==> Creating kind cluster..."
scripts/kind/up.sh
echo "==> Bootstrapping GHCR pull secret..."
scripts/kind/ghcr-pull-secret-bootstrap.sh
echo "==> Bootstrapping app secrets from .env..."
scripts/kind/secrets-bootstrap.sh
echo "==> Installing ArgoCD + syncing the app-of-apps..."
scripts/kind/argocd-bootstrap.sh kind

# --- 6. wait for ArgoCD to create the deployments, then for them to roll out ---
echo "==> Waiting for ArgoCD to create + roll out the app pods (this can take a few minutes)..."
for deploy in openlex-api openlex-worker; do
  echo "    waiting for deploy/${deploy} to be created..."
  until kubectl -n "${NAMESPACE}" get deploy "${deploy}" >/dev/null 2>&1; do sleep 5; done
  kubectl -n "${NAMESPACE}" rollout status "deploy/${deploy}" --timeout=600s
done

# --- 7. ingest the corpus ---
echo "==> Ingesting corpus (statutes + cases)..."
scripts/seed/kind-ingest.sh

# --- 8. seed the demo users ---
echo "==> Seeding demo users..."
scripts/seed/kind-seed-demo-users.sh

cat <<'DONE'

==> kind cluster is up and populated. Open access in separate terminals:
    scripts/kind/app-port-forward.sh            # Web UI :5173, API :8000
    scripts/kind/observability-port-forward.sh  # Grafana :3000 (anon Viewer), ArgoCD :8080, Jaeger :16686

    Log in to the app with the DEMO_* credentials from your .env.
    Tear down with scripts/kind/down.sh.
DONE

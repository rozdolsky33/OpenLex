#!/usr/bin/env bash
# One-time-per-cluster imperative install of ArgoCD itself (chicken-and-egg — it can't deploy
# itself from nothing). Everything else is then ArgoCD-managed via the app-of-apps root
# Application this script applies at the end. Usage:
#   scripts/argocd-bootstrap.sh kind
#   scripts/argocd-bootstrap.sh eks-demo
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ENV="${1:-}"
if [[ "${ENV}" != "kind" && "${ENV}" != "eks-demo" ]]; then
  echo "Usage: $0 <kind|eks-demo>" >&2
  exit 1
fi

helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
helm repo update argo >/dev/null

helm upgrade --install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  --values "infra/argocd/install/argocd-values-${ENV}.yaml" \
  --wait

kubectl apply -f "infra/argocd/projects/appproject-${ENV}.yaml"
kubectl apply -f "infra/argocd/root-apps/root-${ENV}.yaml"

echo
echo "ArgoCD installed and root-${ENV} applied. Watch it with:"
echo "  kubectl get application -n argocd -w"
if [[ "${ENV}" == "kind" ]]; then
  echo
  echo "Admin password:"
  echo "  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo"
  echo "Access (in a separate terminal):"
  echo "  kubectl -n argocd port-forward svc/argocd-server 8080:443"
fi

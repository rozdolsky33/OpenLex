#!/usr/bin/env bash
# scripts/eks-demo-observability-port-forward.sh
#
# Prometheus and Jaeger have no built-in authentication and get no Ingress on eks-demo (see
# infra/argocd/apps/eks-demo/ingress-grafana.yaml's header comment and the design spec's
# revised 7.9) -- this is their only access path, mirroring
# scripts/observability-port-forward.sh's existing pattern for kind service-for-service. A
# brand-new file, not an extension of that script -- 7.3's isolation discipline means
# kind-only files never gain eks-demo-specific logic. Requires a kubeconfig context already
# pointed at the eks-demo cluster (`aws eks update-kubeconfig --name <cluster_name> --region
# <region>`, see infra/terraform/README.md's setup sequence) -- unlike kind's script, this
# doesn't assume it's the only cluster in your kubeconfig, so double-check your current
# context before running this.
set -euo pipefail

NAMESPACE="observability"
ARGOCD_NAMESPACE="argocd"

pids=()
cleanup() {
  echo
  echo "Stopping port-forwards..."
  for pid in "${pids[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-grafana 3000:80 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-prometheus 9090:9090 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-alertmanager 9093:9093 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/jaeger 16686:16686 &
pids+=($!)
kubectl port-forward -n "${ARGOCD_NAMESPACE}" svc/argocd-server 8080:443 &
pids+=($!)

echo "Grafana:      http://localhost:3000  (admin password: kubectl -n ${NAMESPACE} get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d)"
echo "Prometheus:   http://localhost:9090  (no auth -- port-forward only, see this script's header comment)"
echo "Alertmanager: http://localhost:9093"
echo "Jaeger:       http://localhost:16686  (no auth -- port-forward only, see this script's header comment)"
echo "ArgoCD:       https://localhost:8080  (admin password: kubectl -n ${ARGOCD_NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d, or the openlex/argocd-admin Secrets Manager password if already rotated)"
echo
echo "Press Ctrl-C to stop all port-forwards."
wait

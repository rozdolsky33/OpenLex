#!/usr/bin/env bash
# Port-forwards every observability UI/endpoint at once — kind has no ingress (see
# infra/kubernetes/README.md), so this replaces juggling six separate `kubectl
# port-forward` terminals. Ctrl-C kills all of them (trap below).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

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
kubectl port-forward -n "${NAMESPACE}" svc/otel-collector-opentelemetry-collector 4318:4318 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/jaeger 16686:16686 &
pids+=($!)
# argocd-server serves both the UI and gRPC API over the same HTTPS port -- see
# scripts/argocd-bootstrap.sh's own port-forward instructions, unified here so it's one
# command instead of a separate terminal.
kubectl port-forward -n "${ARGOCD_NAMESPACE}" svc/argocd-server 8080:443 &
pids+=($!)

echo "Grafana:      http://localhost:3000  (admin password: kubectl -n ${NAMESPACE} get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d)"
echo "Prometheus:   http://localhost:9090"
echo "Alertmanager: http://localhost:9093"
echo "OTLP/HTTP:    http://localhost:4318  (apps/web browser tracing -- see apps/web/src/telemetry.ts)"
echo "Jaeger:       http://localhost:16686"
echo "ArgoCD:       https://localhost:8080  (admin password: kubectl -n ${ARGOCD_NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
echo
echo "Press Ctrl-C to stop all port-forwards."
wait

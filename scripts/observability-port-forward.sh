#!/usr/bin/env bash
# Port-forwards every observability UI/endpoint at once — kind has no ingress (see
# infra/kubernetes/README.md), so this replaces juggling five separate `kubectl
# port-forward` terminals. Ctrl-C kills all of them (trap below).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAMESPACE="observability"

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

echo "Grafana:      http://localhost:3000  (admin password: kubectl -n ${NAMESPACE} get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d)"
echo "Prometheus:   http://localhost:9090"
echo "Alertmanager: http://localhost:9093"
echo "OTLP/HTTP:    http://localhost:4318  (for browser tracing in a later phase)"
echo
echo "Press Ctrl-C to stop all port-forwards."
wait

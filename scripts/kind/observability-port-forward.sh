#!/usr/bin/env bash
# Port-forwards every observability UI/endpoint at once — kind has no ingress (see
# infra/kubernetes/README.md), so this replaces juggling six separate `kubectl
# port-forward` terminals. Ctrl-C kills all of them.
set -euo pipefail
# shellcheck source=scripts/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../_lib.sh"

NAMESPACE="observability"
ARGOCD_NAMESPACE="argocd"

pf "${NAMESPACE}" kube-prometheus-stack-grafana 3000:80
pf "${NAMESPACE}" kube-prometheus-stack-prometheus 9090:9090
pf "${NAMESPACE}" kube-prometheus-stack-alertmanager 9093:9093
pf "${NAMESPACE}" otel-collector-opentelemetry-collector 4318:4318
pf "${NAMESPACE}" jaeger 16686:16686
# argocd-server serves both the UI and gRPC API over the same HTTPS port.
pf "${ARGOCD_NAMESPACE}" argocd-server 8080:443

echo "Grafana:      http://localhost:3000  (anonymous Editor -- full nav, no login)"
echo "Prometheus:   http://localhost:9090"
echo "Alertmanager: http://localhost:9093"
echo "OTLP/HTTP:    http://localhost:4318  (apps/web browser tracing -- see apps/web/src/telemetry.ts)"
echo "Jaeger:       http://localhost:16686"
echo "ArgoCD:       https://localhost:8080  (admin password: kubectl -n ${ARGOCD_NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
pf_wait

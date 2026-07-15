#!/usr/bin/env bash
# scripts/eks/observability-port-forward.sh
#
# Prometheus and Jaeger have no built-in authentication and get no Ingress on eks-demo (see
# infra/argocd/apps/eks-demo/ingress-grafana.yaml's header comment and the design spec's
# revised 7.9) -- this is their only access path. Shares the generic port-forward runner in
# scripts/_lib.sh with kind's script, but carries no kind-specific logic (7.3's isolation
# discipline: kind/eks files never gain each other's environment-specific config). Requires a
# kubeconfig context already pointed at the eks-demo cluster (`aws eks update-kubeconfig --name
# <cluster_name> --region <region>`, see infra/terraform/README.md) -- unlike kind's script,
# this doesn't assume it's the only cluster in your kubeconfig, so double-check your current
# context before running this.
set -euo pipefail
# shellcheck source=scripts/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../_lib.sh"

NAMESPACE="observability"
ARGOCD_NAMESPACE="argocd"

pf "${NAMESPACE}" kube-prometheus-stack-grafana 3000:80
pf "${NAMESPACE}" kube-prometheus-stack-prometheus 9090:9090
pf "${NAMESPACE}" kube-prometheus-stack-alertmanager 9093:9093
pf "${NAMESPACE}" jaeger 16686:16686
pf "${ARGOCD_NAMESPACE}" argocd-server 8080:443

echo "Grafana:      http://localhost:3000  (admin password: kubectl -n ${NAMESPACE} get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d)"
echo "Prometheus:   http://localhost:9090  (no auth -- port-forward only, see this script's header comment)"
echo "Alertmanager: http://localhost:9093"
echo "Jaeger:       http://localhost:16686  (no auth -- port-forward only, see this script's header comment)"
echo "ArgoCD:       https://localhost:8080  (admin password: kubectl -n ${ARGOCD_NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d, or the openlex/argocd-admin Secrets Manager password if already rotated)"
pf_wait

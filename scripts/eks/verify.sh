#!/usr/bin/env bash
# scripts/eks/verify.sh
#
# One-shot "is what I think I applied actually LIVE?" probe for the eks-demo cluster.
#
# Motivated by the 2026-07-16 postmortem (docs/postmortems/) where two separate issues were both
# "config that reports success but isn't live": a VPC-CNI prefix-delegation addon that Terraform
# claimed to apply but never created, and a Grafana PVC that ArgoCD showed as Progressing while
# the pod quietly ran on emptyDir. Nothing errored loudly — the truth only lived in the node's
# max-pods, the aws-node DaemonSet env, the live pod's volume, and each app's real sync/health.
#
# This script gathers exactly those silently-lying facts in one place so you don't re-derive them
# by hand after every `terraform apply` / node roll / ArgoCD sync. Read-only: it only *reads*
# cluster state (no mutations), so it's safe to run any time. Requires kubectl pointed at the
# eks-demo cluster (see docs/infrastructure/eks-argocd-bootstrap.md for `aws eks update-kubeconfig`).
set -euo pipefail

bold() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }

bold "Nodes — instance type, workload, max-pods (pod capacity is the usual EKS constraint)"
kubectl get nodes \
  -L node.kubernetes.io/instance-type,openlex.dev/workload \
  -o custom-columns='NODE:.metadata.name,TYPE:.metadata.labels.node\.kubernetes\.io/instance-type,WORKLOAD:.metadata.labels.openlex\.dev/workload,MAXPODS:.status.allocatable.pods,STATUS:.status.conditions[-1].type' \
  --no-headers | sed 's/^/  /'

bold "VPC-CNI prefix delegation (drives max-pods; the enabling half that silently no-op'd once)"
pd=$(kubectl -n kube-system get ds aws-node \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="ENABLE_PREFIX_DELEGATION")].value}' 2>/dev/null || true)
[ "${pd:-}" = "true" ] && ok "ENABLE_PREFIX_DELEGATION=true" || warn "ENABLE_PREFIX_DELEGATION=${pd:-<unset>} (max-pods will be the low ENI-IP default)"

bold "Pending pods (capacity starvation shows up here first)"
pending=$(kubectl get pods -A --field-selector=status.phase=Pending --no-headers 2>/dev/null || true)
[ -z "$pending" ] && ok "none Pending" || { warn "Pending pods:"; echo "$pending" | sed 's/^/    /'; }

bold "PVCs not Bound (a WaitForFirstConsumer PVC can deadlock an ArgoCD sync — see postmortem)"
# `kubectl get pvc -A` columns: NAMESPACE(1) NAME(2) STATUS(3) VOLUME(4) ... — filter on STATUS.
unbound=$(kubectl get pvc -A --no-headers 2>/dev/null | awk '$3!="Bound"' || true)
[ -z "$unbound" ] && ok "all PVCs Bound" || { warn "unbound PVCs:"; echo "$unbound" | sed 's/^/    /'; }

bold "ArgoCD apps — sync + health (OutOfSync/!Healthy = live doesn't match git)"
kubectl -n argocd get applications \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status' \
  --no-headers 2>/dev/null | sed 's/^/  /'

bold "openlex API reachability (/healthz from inside the cluster)"
code=$(kubectl -n openlex exec deploy/openlex-api -- \
  sh -c "curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz" 2>/dev/null || echo "ERR")
[ "$code" = "200" ] && ok "/healthz 200" || warn "/healthz returned '$code'"

printf '\n'

#!/usr/bin/env bash
# Port-forwards openlex-web and openlex-api at once, mirroring
# scripts/observability-port-forward.sh's pattern -- kind has no ingress (see
# infra/kubernetes/README.md), so this is how the web UI (deployed by
# infra/kubernetes/overlays/kind, loaded via scripts/kind-load-images.sh) becomes reachable
# from a developer's own browser. Ctrl-C kills both (trap below).
#
# The port numbers are not arbitrary: apps/web's Dockerfile bakes
# VITE_API_BASE_URL=http://localhost:8000 (see infra/kubernetes/base/web/deployment.yaml) into
# the browser bundle at dev-server-start, evaluated client-side -- so openlex-api must be
# forwarded to localhost:8000 for the web UI to actually reach it, not just any local port.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAMESPACE="openlex"

pids=()
cleanup() {
  echo
  echo "Stopping port-forwards..."
  for pid in "${pids[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

kubectl port-forward -n "${NAMESPACE}" svc/openlex-web 5173:80 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/openlex-api 8000:80 &
pids+=($!)

echo "Web: http://localhost:5173"
echo "API: http://localhost:8000  (docs at /docs)"
echo
echo "Press Ctrl-C to stop all port-forwards."
wait

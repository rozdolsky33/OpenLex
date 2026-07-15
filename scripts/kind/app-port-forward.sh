#!/usr/bin/env bash
# Port-forwards openlex-web and openlex-api at once — kind has no ingress (see
# infra/kubernetes/README.md), so this is how the web UI becomes reachable from a developer's
# own browser. Ctrl-C kills both.
#
# The port numbers are not arbitrary: apps/web's Dockerfile bakes
# VITE_API_BASE_URL=http://localhost:8000 (see infra/kubernetes/base/web/deployment.yaml) into
# the browser bundle at dev-server-start, evaluated client-side -- so openlex-api must be
# forwarded to localhost:8000 for the web UI to actually reach it, not just any local port.
set -euo pipefail
# shellcheck source=scripts/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../_lib.sh"

NAMESPACE="openlex"

pf "${NAMESPACE}" openlex-web 5173:80
pf "${NAMESPACE}" openlex-api 8000:80

echo "Web: http://localhost:5173"
echo "API: http://localhost:8000  (docs at /docs)"
pf_wait

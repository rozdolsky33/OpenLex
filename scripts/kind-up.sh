#!/usr/bin/env bash
# Idempotent: create the local `openlex` kind cluster if it doesn't already exist.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CLUSTER_NAME="openlex"

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "kind cluster '${CLUSTER_NAME}' already exists."
else
  kind create cluster --name "${CLUSTER_NAME}" --config infra/kubernetes/kind/kind-config.yaml
fi

kubectl config use-context "kind-${CLUSTER_NAME}"
echo "kubectl context set to kind-${CLUSTER_NAME}."

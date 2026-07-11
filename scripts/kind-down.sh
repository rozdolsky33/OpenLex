#!/usr/bin/env bash
# Tear down the local `openlex` kind cluster (mirrors scripts/kind-up.sh).
set -euo pipefail

CLUSTER_NAME="openlex"
kind delete cluster --name "${CLUSTER_NAME}"

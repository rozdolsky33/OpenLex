#!/usr/bin/env bash
# Build apps/api, apps/worker, and apps/web images and load them into the `openlex` kind
# cluster — kind can't pull from nowhere, so this replaces `docker push`. Re-run after code
# changes; tags are fixed (`kind-local`) to match
# infra/kubernetes/overlays/kind/kustomization.yaml's images: block, so ArgoCD's selfHeal
# won't fight over a changing tag — just re-run this and delete the pod (or `kubectl rollout
# restart`) to pick up the new image.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

CLUSTER_NAME="openlex"

docker build -f apps/api/Dockerfile -t openlex-api:kind-local .
docker build -f apps/worker/Dockerfile -t openlex-worker:kind-local .
# Build context is apps/web itself (see apps/web/Dockerfile's own note) -- not the repo root.
docker build -f apps/web/Dockerfile -t openlex-web:kind-local apps/web

kind load docker-image openlex-api:kind-local --name "${CLUSTER_NAME}"
kind load docker-image openlex-worker:kind-local --name "${CLUSTER_NAME}"
kind load docker-image openlex-web:kind-local --name "${CLUSTER_NAME}"

echo "Loaded openlex-api:kind-local, openlex-worker:kind-local, and openlex-web:kind-local into kind cluster '${CLUSTER_NAME}'."

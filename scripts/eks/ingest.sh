#!/usr/bin/env bash
# scripts/eks/ingest.sh
#
# Ingest the statute + case-law corpus into the *EKS* cluster -- the AWS analogue of
# scripts/seed/kind-ingest.sh and scripts/compose/ingest.sh. Runs the worker's ingestion CLI
# *inside* the running openlex-worker pod, which already has DATABASE_URL + NY_OPEN_LEG_API_KEY
# via `envFrom: openlex-secrets` (populated on EKS by External Secrets from AWS Secrets Manager,
# not a bootstrap script).
#
# Needed because nothing else ingests on EKS: with empty documents/chunks tables, hybrid
# retrieval returns nothing and every /query hard-abstains ("NO CONFIDENT ANSWER FOUND") even
# though the stack is otherwise healthy. Run once after the app pods are up on a fresh cluster.
# Idempotent -- immutable (source, source_id, version) rows mean a rerun is a no-op unless the
# source text changed.
#
# SAFETY: compose, kind, and EKS all use the `openlex` namespace, so this guards on the current
# kube-context pointing at the EKS cluster before touching anything -- running the wrong cluster's
# ingest is a real foot-gun.
#
# Usage: scripts/eks/ingest.sh [statutes|cases|all]   (default: all)
set -euo pipefail

NAMESPACE="openlex"
SOURCE="${1:-all}"
EXPECTED_CONTEXT_MATCH="cluster/openlex-eks-demo"

ctx="$(kubectl config current-context 2>/dev/null || true)"
if [[ "$ctx" != *"$EXPECTED_CONTEXT_MATCH"* ]]; then
  echo "REFUSING: current kube-context is '$ctx', which is not the EKS cluster" >&2
  echo "  (expected it to contain '$EXPECTED_CONTEXT_MATCH')." >&2
  echo "  Point kubectl at EKS first: aws eks update-kubeconfig --name openlex-eks-demo --region us-east-1" >&2
  exit 1
fi

echo "Ingesting '${SOURCE}' into EKS (context: ${ctx})..."
kubectl -n "${NAMESPACE}" exec deploy/openlex-worker -- \
  uv run --frozen python -m openlex_worker ingest --source "${SOURCE}"

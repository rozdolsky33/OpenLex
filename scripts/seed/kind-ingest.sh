#!/usr/bin/env bash
# Ingest the statute + case-law corpus into the *kind* cluster -- the Kubernetes analogue of
# scripts/compose/ingest.sh (which only targets docker-compose). Runs the worker's ingestion
# CLI *inside* the running openlex-worker pod, which already has DATABASE_URL +
# NY_OPEN_LEG_API_KEY via `envFrom: openlex-secrets` (populated by
# scripts/kind/secrets-bootstrap.sh).
#
# Needed because nothing else ingests on kind: with empty documents/chunks tables, hybrid
# retrieval returns nothing and every /query hard-abstains ("NO CONFIDENT ANSWER FOUND") even
# though the stack is otherwise healthy. Run once after the app pods are up on a fresh cluster.
# Idempotent -- immutable (source, source_id, version) rows mean a rerun is a no-op unless the
# source text changed.
#
# Usage: scripts/seed/kind-ingest.sh [statutes|cases|all]   (default: all)
set -euo pipefail

NAMESPACE="openlex"
SOURCE="${1:-all}"

kubectl -n "${NAMESPACE}" exec deploy/openlex-worker -- \
  uv run --frozen python -m openlex_worker ingest --source "${SOURCE}"

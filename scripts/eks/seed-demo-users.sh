#!/usr/bin/env bash
# scripts/eks/seed-demo-users.sh
#
# Seed/refresh the three fixed tier demo users into the *EKS* cluster -- the AWS analogue of
# scripts/seed/kind-seed-demo-users.sh and scripts/seed/seed-demo-users.sh. Runs the same seed
# module (openlex_api.seed_demo_users) *inside* the running openlex-api pod, which already has the
# DEMO_{SILVER,GOLD,PLATINUM}_{EMAIL,PASSWORD} env vars via `envFrom: openlex-secrets` (populated
# on EKS by External Secrets from AWS Secrets Manager).
#
# Needed because nothing else seeds users on EKS: with an empty `users` table, /auth/login returns
# 401 for the demo credentials even though the stack is otherwise healthy (registration is
# disabled -- these three tier-gated users are the only logins). Run once after the app pods are
# up on a fresh cluster. Idempotent -- rerun any time to reset a demo user's password/tier and
# zero their quota window.
#
# SAFETY: compose, kind, and EKS all use the `openlex` namespace, so this guards on the current
# kube-context pointing at the EKS cluster before touching anything.
set -euo pipefail

NAMESPACE="openlex"
EXPECTED_CONTEXT_MATCH="cluster/openlex-eks-demo"

ctx="$(kubectl config current-context 2>/dev/null || true)"
if [[ "$ctx" != *"$EXPECTED_CONTEXT_MATCH"* ]]; then
  echo "REFUSING: current kube-context is '$ctx', which is not the EKS cluster" >&2
  echo "  (expected it to contain '$EXPECTED_CONTEXT_MATCH')." >&2
  echo "  Point kubectl at EKS first: aws eks update-kubeconfig --name openlex-eks-demo --region us-east-1" >&2
  exit 1
fi

echo "Seeding demo users into EKS (context: ${ctx})..."
kubectl -n "${NAMESPACE}" exec deploy/openlex-api -- \
  uv run --frozen python -m openlex_api.seed_demo_users

#!/usr/bin/env bash
# Seed/refresh the three fixed tier demo users into the *kind* cluster -- the Kubernetes
# analogue of scripts/seed/seed-demo-users.sh (which only targets docker-compose). Runs the
# same seed module *inside* the running openlex-api pod, which already has the DEMO_* env vars
# via `envFrom: openlex-secrets` (populated by scripts/kind/secrets-bootstrap.sh).
#
# Needed because nothing else seeds users on kind: with an empty `users` table, /auth/login
# returns 401 for the demo credentials even though the stack is otherwise healthy. Run this
# once after the app pods are up on a fresh cluster. Idempotent -- rerun any time to reset a
# demo user's password/tier and zero their quota window.
set -euo pipefail

NAMESPACE="openlex"

kubectl -n "${NAMESPACE}" exec deploy/openlex-api -- \
  uv run --frozen python -m openlex_api.seed_demo_users

#!/usr/bin/env bash
# Master bring-up for the docker-compose dev stack: one command that gets you from a clean
# checkout to a working, populated app. Chains the individual compose scripts in order:
#
#   1. guard: .env exists with the required API keys set
#   2. scripts/compose/bootstrap.sh   -- uv sync, pre-commit install, docker compose up --build
#   3. wait for the API to report healthy
#   4. scripts/compose/ingest.sh all  -- ingest statutes + cases into Postgres
#   5. scripts/seed/seed-demo-users.sh -- create the tier-gated demo logins
#
# Idempotent -- safe to re-run (each step is a no-op / refresh if already done).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# --- 1. .env guard: bring-up is pointless without the keys ingest/query need ---
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example." >&2
  echo "Set ANTHROPIC_API_KEY and NY_OPEN_LEG_API_KEY in .env, then re-run this script." >&2
  exit 1
fi
for key in ANTHROPIC_API_KEY NY_OPEN_LEG_API_KEY; do
  val="$(sed -n -E "s/^${key}=(.*)$/\1/p" .env | head -1)"
  if [ -z "${val}" ]; then
    echo "ERROR: ${key} is empty in .env -- set it before bringing the stack up." >&2
    exit 1
  fi
done

# --- 2. bootstrap the stack (finds the existing .env, syncs, builds, starts containers) ---
echo "==> Bootstrapping docker-compose stack..."
scripts/compose/bootstrap.sh

# --- 3. wait for the API to report healthy ---
echo "==> Waiting for the API (http://localhost:8000/healthz) to report ok..."
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8000/healthz 2>/dev/null | grep -q '"status":"ok"'; then
    echo "    API is healthy."
    break
  fi
  sleep 3
done

# --- 4. ingest the corpus ---
echo "==> Ingesting corpus (statutes + cases)..."
scripts/compose/ingest.sh all

# --- 5. seed the demo users ---
echo "==> Seeding demo users..."
scripts/seed/seed-demo-users.sh

cat <<'DONE'

==> docker-compose stack is up and populated.
    Web UI : http://localhost:5173
    API    : http://localhost:8000  (docs at /docs)
    Grafana: http://localhost:3000   (anonymous Viewer)
    Log in with the DEMO_* credentials from your .env.
DONE

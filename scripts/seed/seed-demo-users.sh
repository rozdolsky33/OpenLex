#!/usr/bin/env bash
# Seed/refresh the three fixed tier demo users (Silver/Gold/Platinum) against the running
# docker-compose stack. Idempotent -- rerun any time to reset a demo user's password/tier and
# zero their quota window. Reads DEMO_SILVER_EMAIL/etc. from .env (see .env.example).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# -T: no pseudo-TTY -- same reasoning as scripts/compose/ingest.sh, works under CI too.
docker compose exec -T api uv run --frozen python -m openlex_api.seed_demo_users

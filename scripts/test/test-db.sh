#!/usr/bin/env bash
# Manage the ephemeral db-test docker-compose service that tests/integration runs against
# (real Postgres+pgvector, matching tests/integration/conftest.py's TEST_DATABASE_URL default
# of postgresql+asyncpg://openlex_test@127.0.0.1:5544/openlex_test — no env var needed).
# Usage: scripts/test/test-db.sh [up|down|reset]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

CMD="${1:-up}"

_wait_healthy() {
  echo "Waiting for db-test to become healthy..."
  until [ "$(docker compose --profile test ps -q db-test | xargs -I{} docker inspect -f '{{.State.Health.Status}}' {})" = "healthy" ]; do
    sleep 1
  done
  echo "db-test is up on 127.0.0.1:5544."
}

case "$CMD" in
  up)
    docker compose --profile test up -d db-test
    _wait_healthy
    ;;
  down)
    docker compose --profile test down db-test
    ;;
  reset)
    # tmpfs data dir means down+up already gives a clean schema; explicit for intent (e.g.
    # after editing migrations/postgres/0001_init.sql).
    docker compose --profile test down db-test
    docker compose --profile test up -d db-test
    _wait_healthy
    ;;
  *)
    echo "Usage: $0 <up|down|reset>" >&2
    exit 1
    ;;
esac

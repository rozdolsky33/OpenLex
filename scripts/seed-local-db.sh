#!/usr/bin/env bash
# Apply the Postgres schema to a fresh local db container (docker-compose's db service
# already does this automatically via docker-entrypoint-initdb.d on first boot — this script
# is for re-applying after a manual `docker compose down -v` / schema change without a
# full volume reset). Applies every migrations/postgres/*.sql file in sorted (numeric prefix)
# order, same as docker-entrypoint-initdb.d does on first boot.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

for migration in migrations/postgres/*.sql; do
  echo "Applying $migration..."
  docker compose exec -T db psql -U openlex -d openlex < "$migration"
done

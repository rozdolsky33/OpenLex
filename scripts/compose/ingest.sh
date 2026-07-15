#!/usr/bin/env bash
# Run the ingestion pipeline against the running docker-compose stack.
# Usage: scripts/compose/ingest.sh [statutes|cases|all]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

SOURCE="${1:-all}"

# -T: no pseudo-TTY -- needed so this works under CI (GitHub Actions `run:` steps have no
# TTY attached) as well as interactively; the ingest command itself takes no stdin either way.
docker compose exec -T worker uv run --frozen python -m openlex_worker ingest --source "$SOURCE"

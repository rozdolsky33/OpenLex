#!/usr/bin/env bash
# Run the ingestion pipeline against the running docker-compose stack.
# Usage: scripts/ingest.sh [statutes|cases|all]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SOURCE="${1:-all}"

if [ ! -f apps/worker/src/openlex_worker/__main__.py ]; then
  echo "openlex_worker has no __main__.py yet — the ingestion entrypoint isn't implemented." >&2
  echo "See the data-ingestion agent and pipelines/ingestion/ for the pieces that exist." >&2
  exit 1
fi

# -T: no pseudo-TTY -- needed so this works under CI (GitHub Actions `run:` steps have no
# TTY attached) as well as interactively; the ingest command itself takes no stdin either way.
docker compose exec -T worker uv run --frozen python -m openlex_worker ingest --source "$SOURCE"

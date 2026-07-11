#!/usr/bin/env bash
# Run the golden-question legal-accuracy evaluation harness against a running API.
# Requires the API to already be up (docker compose up -d db api) and ingested
# (scripts/ingest.sh statutes) -- this hits POST /query for real, including real Anthropic
# calls. Set EVAL_API_BASE_URL to point at something other than http://localhost:8000.
# Usage: scripts/evaluate.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -f tests/evaluation/golden_questions.yaml ]; then
  echo "tests/evaluation/golden_questions.yaml doesn't exist yet — nothing to evaluate." >&2
  exit 1
fi

# -m evaluation overrides the root pyproject.toml's default "-m 'not evaluation'" (this suite
# is excluded from the default `uv run pytest` run since it costs real API calls).
uv run --package openlex-api pytest tests/evaluation -v -m evaluation

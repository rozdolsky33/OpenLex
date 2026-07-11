#!/usr/bin/env bash
# Run the golden-question legal-accuracy evaluation harness against a running API.
# Usage: scripts/evaluate.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -f tests/evaluation/golden_questions.yaml ]; then
  echo "tests/evaluation/golden_questions.yaml doesn't exist yet — nothing to evaluate." >&2
  exit 1
fi

uv run --package openlex-api pytest tests/evaluation -v

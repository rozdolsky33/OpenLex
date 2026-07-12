#!/usr/bin/env bash
# First-time local setup: copy .env, sync the uv workspace, and bring up the docker stack.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — edit it to set ANTHROPIC_API_KEY and NY_OPEN_LEG_API_KEY before continuing."
fi

uv sync --all-packages
uv run pre-commit install
docker compose up --build -d
docker compose ps

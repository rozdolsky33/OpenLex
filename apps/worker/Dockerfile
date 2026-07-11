# Build context is the repo root (see docker-compose.yml) so this can install
# the uv workspace (root pyproject.toml/uv.lock + local package dependencies).
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

WORKDIR /repo

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY packages/legal_models/pyproject.toml packages/legal_models/pyproject.toml
COPY packages/legal_retrieval/pyproject.toml packages/legal_retrieval/pyproject.toml
COPY packages/legal_generation/pyproject.toml packages/legal_generation/pyproject.toml
COPY packages/legal_parsing/pyproject.toml packages/legal_parsing/pyproject.toml
COPY packages/shared/pyproject.toml packages/shared/pyproject.toml

RUN uv sync --frozen --package openlex-worker

COPY . .

WORKDIR /repo/apps/worker
CMD ["uv", "run", "--frozen", "python", "-m", "openlex_worker"]

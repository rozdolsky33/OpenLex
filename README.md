# OpenLex — NY Landlord-Tenant Legal Research Assistant (POC)

A retrieval-augmented legal *research* assistant scoped to New York landlord-tenant
law. It answers questions by retrieving relevant statute and case-law passages and
asking Claude to answer **only** from that retrieved context, with citations.

This is **legal information, not legal advice**, and is not a substitute for a
licensed attorney. See the disclaimer shown in the UI on every response.

## Data sources

- **Statutes**: [NY Open Legislation API](https://legislation.nysenate.gov/api/3/) —
  RPAPL (eviction/holdover), RPL (warranty of habitability), GOL (security deposits).
- **Cases**: a hand-curated seed file of real NY landlord-tenant decisions
  (`pipelines/ingestion/ny_case_law/seed_cases.json`, not yet created). NY Official Reports
  has no public API and blocks automated fetches, so case law is not scraped live in this POC.

## Prerequisites

- Docker + Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package/workspace manager)
- An Anthropic API key (https://console.anthropic.com/)
- A free NY Open Legislation API key (https://legislation.nysenate.gov/static/docs/html/laws.html — self-serve signup)

## Setup

```bash
scripts/bootstrap.sh
# or manually:
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY and NY_OPEN_LEG_API_KEY
uv sync --all-packages
docker compose up --build
```

Once the containers are up, ingest the data:

```bash
scripts/ingest.sh all
```

Then open the UI at http://localhost:5173 (API at http://localhost:8000, docs at `/docs`).

## Repository layout

This is a **monorepo** (modular monolith, not microservices) — see
`docs/decisions/0001-monorepo-restructure.md` for the full rationale.

- `apps/api/` — FastAPI service (routers, request handling). Imports from `packages/`.
- `apps/worker/` — scheduled ingestion runner. Imports from `pipelines/` and `packages/`.
- `apps/web/` — Vite + React + TypeScript chat UI (not yet scaffolded).
- `packages/` — reusable domain libraries: `legal_models` (schemas/ORM), `legal_retrieval`
  (hybrid pgvector + Postgres FTS), `legal_generation` (grounded-answer contract),
  `legal_parsing` (chunking/normalization), `shared` (config, DB session).
- `pipelines/ingestion/` — per-source adapters (`ny_legislation/`, `ny_case_law/`), all
  producing the same normalized document shape.
- `ml/` — prompt templates, evaluation assets, model cards. Not production request-handling
  code.
- `schemas/` — versioned JSON Schema for the core data shapes (document, citation, retrieval
  result, answer).
- `migrations/postgres/` — Postgres schema (pgvector + full-text search indexes).
- `infra/` — deployment config (stubbed — this runs on local `docker-compose` today).
- `tests/` — integration, end-to-end, and the golden-question legal-accuracy evaluation
  harness. Unit tests live next to their code (`apps/*/tests/`, `packages/*/tests/`).
- `docker-compose.yml` — Postgres (pgvector), api, worker, web.

See `tests/evaluation/` for the (not yet populated) manual evaluation checklist, and
`docs/` for architecture documentation and decision records.

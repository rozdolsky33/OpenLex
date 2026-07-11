# OpenLex — NY Landlord-Tenant Legal Research Assistant (POC)

[![api](https://github.com/rozdolsky33/OpenLex/actions/workflows/api.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/api.yml)
[![pipelines](https://github.com/rozdolsky33/OpenLex/actions/workflows/pipelines.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/pipelines.yml)
[![security](https://github.com/rozdolsky33/OpenLex/actions/workflows/security.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/security.yml)
[![web](https://github.com/rozdolsky33/OpenLex/actions/workflows/web.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/web.yml)
[![evaluation](https://github.com/rozdolsky33/OpenLex/actions/workflows/evaluation.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/evaluation.yml)
[![evaluation report](https://img.shields.io/badge/evaluation%20report-live%20on%20pages-blue)](https://rozdolsky33.github.io/OpenLex/)

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

See `docs/` for architecture documentation and decision records.

## CI/CD and legal-accuracy evaluation

The badges above track two different things, and it's worth being explicit about what each
one is checking and why:

- **`api` / `pipelines` / `security` / `web`** are standard PR gates — lint, typecheck, unit
  and integration tests, dependency-vulnerability scanning — scoped by path filter so each
  only runs when the code it covers actually changed. These tell you the code is *correct and
  safe*, not that its answers are *any good*.
- **`evaluation`** is different: it's a legal-accuracy regression suite, not a code-quality
  check. `tests/evaluation/golden_questions.yaml` holds a curated set of real NY
  landlord-tenant questions with known-correct expected citations; the suite fires each one at
  a live stack (Postgres + the API + real Claude calls) and checks that retrieval + generation
  actually finds and cites the right statute. In a system whose entire value proposition is
  "only answer from retrieved context, with correct citations," this is the check that matters
  most — a green `api` badge says nothing about whether the retrieval pipeline just started
  citing the wrong statute for a given question.

**How it's set up, and why it's two-tiered:**

1. **On every PR** touching retrieval/generation/prompts: an automatic, single-pass run
   against `claude-haiku-4-5` (not the production model) — fast, cheap, real feedback on
   whether a change broke retrieval or generation, without the cost of the full comparison
   below.
2. **On demand only** (`gh workflow run evaluation.yml --ref main`, or Actions tab ->
   `evaluation` -> *Run workflow*) — a heavier run: the same 21 questions against **both**
   Haiku and the actual production model (`claude-sonnet-4-5`), a check of whether any of the
   underlying NY statute text has changed since it was last ingested, and a published report.
   This is manual rather than automatic-on-merge specifically to control real Anthropic API
   spend during active development — see
   [ADR-0004](docs/decisions/0004-golden-question-report-and-pages.md) for the full reasoning
   and cost breakdown.

The manual run publishes a **live report to GitHub Pages**:
**[rozdolsky33.github.io/OpenLex](https://rozdolsky33.github.io/OpenLex/)** — showing, per
question, what was expected vs. what each model actually answered and cited; a historical
trend across past runs; where Haiku and Sonnet's answers *diverge* (a direct signal on the
cost/accuracy tradeoff of using Haiku in CI while production runs Sonnet); and whether any
seeded statute's live text has drifted from the snapshot the golden answers were graded
against. See `tests/evaluation/README.md` for how to run the suite locally, and
[ADR-0004](docs/decisions/0004-golden-question-report-and-pages.md) for the full design
(why a git-native `gh-pages` history store, why divergence is flagged the way it is, why the
freshness check runs before any Claude spend).

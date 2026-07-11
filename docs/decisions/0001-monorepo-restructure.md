# 0001: Adopt a monorepo (modular monolith) structure, rebrand to OpenLex

- **Status**: Proposed — migration not yet executed, pending review of this doc
- **Date**: 2026-07-10

## Context

The project started as a minimal POC: a `backend/` FastAPI service (mostly scaffolded —
config, DB schema/models, and statute ingestion exist; routers, retrieval, generation, and
`main.py` do not yet) and an empty `frontend/` directory, with per-service `requirements.txt`
and no monorepo tooling. As the scope grows to cover multiple ingestion sources, a real
retrieval/generation pipeline, evaluation, and eventually a scheduled worker, the flat
`backend/` + `frontend/` split doesn't give clear boundaries between "reusable legal-domain
logic," "operational data pipelines," and "the thing that serves HTTP requests."

The name **LegoraAI** is also being retired in favor of **OpenLex** as part of this change
(decided alongside this restructure, not derived from it). The working directory has already
been renamed on disk to `OpenLex/` — this doc only needs to cover renaming *inside* the repo
(packages, services, docker-compose names, env vars, docs).

## Decision

Adopt a **monorepo, modular-monolith** layout — `apps/`, `packages/`, `pipelines/`, `ml/`,
`schemas/`, `migrations/`, `infra/`, `tests/`, `scripts/`, `docs/`, `.github/workflows/` —
with clear import boundaries between layers, one root `pyproject.toml` + `uv.lock` managing a
`uv` workspace, and per-app/package `pyproject.toml` files for local dependencies.

**Monorepo does not mean tightly coupled code.** Packages stay import-only (no HTTP/UI
concerns), each app gets its own Dockerfile, and CI jobs are path-filtered so a change to
`apps/web` doesn't run the Python test suite.

### Decisions made and why

| Decision | Choice | Why |
|---|---|---|
| Repo shape | Monorepo, modular monolith (not microservices, not multirepo) | Single team, single deploy target right now. Splitting into services (citation service, embedding service, etc.) or repos before there's a reason to (separate teams, separate release cadence, separate compliance boundary) adds networking/CI/coordination overhead with no current payoff. See "When to reconsider" below. |
| Naming | Rebrand `legora*` → `openlex*` throughout (packages, docker-compose services/db/user, env var prefixes, docs) | Matches the project rename; avoids a permanent mismatch between the repo name and internal package names. |
| Package manager | Migrate from per-service `requirements.txt` to `uv` workspaces (root `pyproject.toml` + `uv.lock`) | `uv` has native workspace support (shared lockfile, per-package deps, fast installs) which is what a Python monorepo with `apps/` + `packages/` needs — `pip -r requirements.txt` per service can't express "packages/legal_models is a local dependency of apps/api." |
| Migration timing | Restructure immediately after this doc is approved, not deferred | The repo has almost no code yet (~400 lines total) — this is the cheapest point at which to move files. Deferring means writing new code against the old layout and migrating it twice. |
| `infra/terraform`, `infra/kubernetes`, `infra/monitoring` | Create with placeholder `README.md` only, no real manifests | The project runs on local `docker-compose` only today. Stubbing keeps the target layout visible (so nobody re-derives "where would k8s config go") without maintaining fake infrastructure config that will drift. |
| `ml/experiments`, `ml/training` | Create with placeholder `README.md`, likely unused near-term | Generation uses the Anthropic API (no model fine-tuning) and embeddings use an off-the-shelf `sentence-transformers` model loaded in-process. No training pipeline is planned. Kept as stubs in case that changes (e.g. embedding fine-tuning on the golden set later). |
| Standalone "model server" | Not included as a service | The pasted reference architecture lists an LLM/embedding model server as its own runtime component. This project calls the Anthropic API for generation and loads `sentence-transformers` in-process (API/worker) for embeddings — no self-hosted model server exists or is planned, so it's omitted rather than stubbed. |
| Object storage | Not included yet | Nothing in the current design writes large binary artifacts (documents are stored as JSONB `raw_snapshot` in Postgres). Add `infra/` object storage config if/when raw source documents (e.g. PDFs) need to be archived outside the DB. |
| DB migrations | `migrations/postgres/` holds the existing single `schema.sql` for now; no Alembic yet | Consistent with the earlier decision to keep DB change management simple until there's more than one schema revision to manage. Alembic remains a documented future addition, not wired up now. |
| `packages/legal_generation` (new, not in the pasted reference) | Added as a fourth domain package alongside `legal_models`, `legal_retrieval`, `legal_parsing` | The "answer only from retrieved context, with citations and a disclaimer, or abstain" contract (`grounded-answer-contract`) is reusable logic needed by both `apps/api` (live queries) and `tests/evaluation` (golden-question eval harness) — it belongs in a package, not duplicated or left inside the API app. |

## Target structure

```
OpenLex/
├── README.md
├── Makefile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── pyproject.toml                 # uv workspace root; shared ruff/mypy/pytest config
├── uv.lock
│
├── apps/
│   ├── api/
│   │   ├── src/openlex_api/
│   │   │   ├── main.py            # FastAPI app
│   │   │   ├── routers/           # query, ingest, health
│   │   │   └── deps.py            # FastAPI dependencies (DB session, settings)
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   ├── web/                       # Vite + React + TS (not yet scaffolded)
│   │   ├── src/
│   │   ├── tests/
│   │   ├── package.json
│   │   └── Dockerfile
│   │
│   └── worker/
│       ├── src/openlex_worker/    # scheduled ingestion runner
│       ├── tests/
│       ├── pyproject.toml
│       └── Dockerfile
│
├── packages/
│   ├── legal_models/               # pydantic + SQLAlchemy: Document, Chunk, Citation, QueryResponse...
│   ├── legal_retrieval/            # hybrid pgvector + Postgres FTS retrieval
│   ├── legal_generation/           # grounded-answer contract: prompt building, citation/abstain logic
│   ├── legal_parsing/              # chunking/normalization of statute & case text
│   └── shared/openlex_shared/      # pydantic-settings config, async DB session factory
│
├── pipelines/
│   ├── ingestion/
│   │   ├── ny_legislation/         # NY Open Legislation API client + seed_statutes.json
│   │   └── ny_case_law/            # hand-curated seed_cases.json (no public API to scrape)
│   ├── normalization/
│   ├── chunking/
│   ├── embeddings/
│   └── indexing/
│
├── ml/
│   ├── experiments/                # placeholder — no training planned yet
│   ├── training/                   # placeholder — no training planned yet
│   ├── prompts/                    # Claude generation prompt templates
│   ├── datasets/
│   │   ├── README.md
│   │   └── manifests/
│   └── model_cards/                # e.g. BAAI/bge-small-en-v1.5 card: dims, licensing, limits
│
├── schemas/                        # versioned JSON Schema, exported from legal_models
│   ├── legal_document.schema.json
│   ├── legal_citation.schema.json
│   ├── retrieval_result.schema.json
│   └── answer.schema.json
│
├── migrations/
│   └── postgres/
│       └── 0001_init.sql           # current schema.sql; Alembic deferred (see table above)
│
├── infra/
│   ├── docker/
│   ├── terraform/README.md         # stub
│   ├── kubernetes/README.md        # stub
│   └── monitoring/README.md        # stub (prometheus/grafana)
│
├── tests/
│   ├── integration/                # cross-package tests hitting a real Postgres
│   ├── end_to_end/
│   ├── evaluation/                 # golden_questions.yaml + eval harness
│   └── fixtures/
│
├── scripts/
│   ├── bootstrap.sh
│   ├── ingest.sh
│   ├── evaluate.sh
│   └── seed-local-db.sh
│
├── docs/
│   ├── architecture.md
│   ├── data-sources.md
│   ├── legal-safety.md
│   ├── evaluation.md
│   └── decisions/
│       └── 0001-monorepo-restructure.md   # this file
│
└── .github/
    └── workflows/
        ├── api.yml
        ├── web.yml
        ├── pipelines.yml
        ├── evaluation.yml
        └── security.yml
```

## Repository boundaries

- **`apps/`** — independently deployable, independently Dockerized. `apps/api` must not
  contain parsing, retrieval, or generation logic directly — it imports from `packages/` and
  wires HTTP routes around them. `apps/worker` imports from `pipelines/` and `packages/` to
  run scheduled ingestion; it is *not* a place for one-off logic that only `apps/api` uses.
- **`packages/`** — pure Python libraries, no HTTP/UI concerns, importable by any app:
  `from legal_retrieval import HybridRetriever`, `from legal_models import Document, Citation`.
  If a package needs `fastapi` or `httpx`-to-our-own-API, that's a sign the code belongs in
  `apps/` instead.
- **`pipelines/`** — operational data workflows (ingest → normalize → chunk → embed → index).
  Each source gets its own adapter (`pipelines/ingestion/ny_legislation/`,
  `pipelines/ingestion/ny_case_law/`) and all adapters must emit the same normalized
  `legal_models.Document` shape, so retrieval never needs to know which source a chunk came
  from.
- **`ml/`** — experimentation and prompt/eval assets, not production request-handling code.
  If generation-prompt logic becomes load-bearing for `apps/api`, the *template* stays in
  `ml/prompts/` but the *code that calls it* lives in `packages/legal_generation`.
- **`schemas/`** — stable, versioned JSON Schema for `Document`, `Citation`,
  `RetrievalResult`, and `Answer`, generated from `packages/legal_models` where possible
  rather than hand-duplicated, so the two can't silently drift.
- **`migrations/postgres/`** — schema change history. Currently one file; add Alembic when a
  second real migration is needed.
- **`infra/`** — deployment config. Stubbed today (see decisions table); fill in when the
  project actually needs to run outside `docker-compose`.
- **`tests/`** — cross-cutting tests that don't belong to a single package/app: integration,
  end-to-end, and the golden-question legal-accuracy evaluation harness. Unit tests live next
  to the code they test (`apps/api/tests/`, `packages/*/tests/`).

## Service topology (unchanged scope, just relocated)

```
Browser
  │
  ▼
apps/web (Vite/React/TS)
  │
  ▼
apps/api (FastAPI)
  ├── PostgreSQL + pgvector   (documents, chunks — hybrid retrieval)
  └── Anthropic API           (grounded generation)

apps/worker (scheduled)
  ├── pipelines/ingestion/*   (NY Open Legislation, hand-curated case seed)
  ├── pipelines/chunking, pipelines/embeddings
  └── writes into PostgreSQL + pgvector
```

No standalone model-serving component and no object storage — see decisions table for why.

## Migration mapping

| Current | New |
|---|---|
| `backend/app/config.py` | `packages/shared/src/openlex_shared/config.py` |
| `backend/app/db.py` | `packages/shared/src/openlex_shared/db.py` |
| `backend/app/models.py` | `packages/legal_models/src/legal_models/orm.py` |
| `backend/app/schemas.py` | `packages/legal_models/src/legal_models/schemas.py` (+ exported `schemas/*.json`) |
| `backend/app/db/schema.sql` | `migrations/postgres/0001_init.sql` |
| `backend/app/ingestion/open_legislation.py` | `pipelines/ingestion/ny_legislation/client.py` |
| `backend/app/ingestion/seed_statutes.json` | `pipelines/ingestion/ny_legislation/seed_statutes.json` |
| `backend/app/ingestion/seed_cases.json` (planned, not yet created) | `pipelines/ingestion/ny_case_law/seed_cases.json` |
| `backend/app/retrieval/` (empty) | `packages/legal_retrieval/src/legal_retrieval/` |
| `backend/app/generation/` (empty) | `packages/legal_generation/src/legal_generation/` |
| `backend/app/routers/` (empty) | `apps/api/src/openlex_api/routers/` |
| `backend/app/main.py` (missing) | `apps/api/src/openlex_api/main.py` |
| `backend/scripts/` (empty, `ingest_cli.py` planned) | `apps/worker/src/openlex_worker/` + `scripts/ingest.sh` (manual trigger) |
| `backend/tests/` | `apps/api/tests/`, `packages/*/tests/` (unit) |
| `backend/tests/golden/golden_questions.yaml` (planned) | `tests/evaluation/golden_questions.yaml` |
| `backend/Dockerfile` | `apps/api/Dockerfile` |
| `backend/requirements.txt` | root `pyproject.toml`/`uv.lock` + per-app `pyproject.toml` |
| `frontend/` | `apps/web/` |
| `docker-compose.yml`, `.env`/`.env.example`, `README.md`, `CLAUDE.md` | stay at root; updated for new paths, `openlex` naming, and `uv` commands |

`.claude/agents/*.md` and `.claude/skills/*/SKILL.md` created earlier reference the old
`backend/app/...` paths — they need a follow-up update pass to point at the new locations.
That update is **not** part of this doc; it happens after the migration lands.

## CI strategy

Path-filtered GitHub Actions jobs so a change to one area doesn't trigger the whole suite:

```yaml
on:
  pull_request:
    paths:
      - "apps/api/**"
      - "packages/**"
      - "schemas/**"
```

Pipeline stages: lint → unit tests → schema validation → integration tests → container build →
retrieval/generation evaluation → security scanning → deploy. The evaluation stage
(`tests/evaluation`, backed by `packages/legal_retrieval` + `packages/legal_generation`) only
runs when those paths, or `ml/prompts/**`, change — it's slower than a unit-test suite and
shouldn't gate unrelated changes (e.g. a `apps/web` tweak).

## Data does not live in Git

Never commit: full statute/case-law collections, embeddings, model weights, raw scraped
documents, or production evaluation results. Keep only: small test fixtures, dataset
manifests + content hashes, the existing hand-curated seed files (`seed_statutes.json`,
`seed_cases.json` — small, licensed, intentionally checked in), and data-source config.

## When to reconsider multirepo

Revisit this decision if any of these become true: separate teams own web/platform/ML;
components need independent release cycles; access to case-law data must be restricted
per-component; the ingestion pipeline becomes a product other teams consume independently; CI
stays slow despite path filtering; or a component acquires a different compliance/security
boundary than the rest of the repo. Until then, a later split (e.g.
`openlex-app` / `openlex-data-platform` / `openlex-ml`) would trade schema-version
synchronization, cross-repo PRs, and local-dev friction for isolation the project doesn't need
yet.

## Deferred / explicitly out of scope for this doc

- Executing the migration (file moves, `uv` workspace init, docker-compose/env/README updates)
- Updating `.claude/agents/` and `.claude/skills/` to the new paths
- Alembic migration tooling
- Real `infra/terraform`, `infra/kubernetes`, `infra/monitoring` config
- Content for `docs/architecture.md`, `docs/data-sources.md`, `docs/legal-safety.md`,
  `docs/evaluation.md` (structure only, in this doc's target tree)

## Next steps

1. You review this doc.
2. On approval, execute the migration: create the new tree, move files per the mapping table,
   stand up the `uv` workspace (root + per-app/package `pyproject.toml`), update
   `docker-compose.yml`/`.env`/`.env.example`/`README.md`/`CLAUDE.md` for the new paths and
   `openlex` naming, and verify `docker compose up --build` still boots.
3. Update `.claude/agents/` and `.claude/skills/` to point at the new locations.
4. Resume the previously-scoped dev-hygiene work (ruff/mypy/pytest config, slash commands,
   remaining `docs/` content) inside the new structure.

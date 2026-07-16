# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

OpenLex is a retrieval-augmented legal *research* assistant (POC) scoped to New York
landlord-tenant law. It retrieves statute and case-law passages and asks Claude to answer
**only** from that retrieved context, with citations. This is legal information, not legal
advice — every response must carry the disclaimer defined in `legal_models.schemas`
(`DISCLAIMER`).

The repo is a **monorepo, modular monolith** (`apps/` + `packages/` + `pipelines/`, one `uv`
workspace) — see `docs/decisions/0001-monorepo-restructure.md` for the full rationale and a
mapping of where the old `backend/`/`frontend/` code moved to.

## Why this project exists — read before scoping any work

OpenLex is a portfolio POC demonstrating SRE/Platform Engineering skills applied to an
AI-powered product — here, a legal-tech RAG system for a hypothetical greenfield team. It is
**not** headed for a real GA launch. This changes what "done" means for different parts of
the repo:

- **Legal content (statute/case-law corpus, ToS/privacy copy, eval question coverage) only
  needs to be *credible*, not *complete*.** Enough breadth to demonstrate real hybrid
  retrieval + grounded generation working end-to-end on non-trivial legal text is the bar —
  not exhaustive coverage of NY landlord-tenant law. Don't unilaterally expand corpus/content
  scope; when a GA-checklist item implies "more," default to the smallest slice that proves
  the mechanism works, and confirm before going bigger.
- **SRE/Platform/operational depth is the actual product being demonstrated.** Observability
  (traces/metrics/logs, cost/token tracking per LLM call, symptom-based alerting), reliability
  (quota enforcement, safe rollout/redeploy discipline, GitOps via ArgoCD), incident response,
  and infra-as-code are what this repo exists to showcase. When in doubt about where to spend
  effort, this is almost always the higher-value direction over legal-domain breadth.
- **Real incidents are good material, not just interruptions.** When something breaks during
  ops work (e.g. the 2026-07-14 Docker Desktop disk-exhaustion incident during Phase 5
  ingestion — see `docs/postmortems/`), root-cause it properly and write it up. That's more
  valuable to this project's actual purpose than the feature that was in flight when it broke.

The GA readiness checklist (`docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md`)
still tracks real work, but Phases 4/5 (legal/compliance content, corpus expansion) should be
treated as "reasonable minimum," while Phase 3 (observability) and Phase 6 (CI/CD & infra
hardening) are where continued investment actually serves the project's purpose.

## Current state (important)

The end-to-end statute path — ingest → normalize → chunk → embed → index → hybrid retrieve →
grounded generate — is implemented and wired together (see ADR-0002 for the retrieval/
generation design). What's built:

- `apps/api/src/openlex_api/main.py` is a working FastAPI entrypoint: `/healthz` (DB +
  embedding-model-loaded probe), and the `auth`/`query`/`ingest` routers are mounted. The
  embedding model is preloaded at startup via `lifespan` so it isn't the first request's
  problem.
- `apps/api/src/openlex_api/routers/auth.py` + `apps/api/src/openlex_api/auth.py` implement
  simple JWT auth: `POST /auth/register` (email/password, bcrypt-hashed), `POST /auth/login`
  (OAuth2 password form, returns a 60-minute HS256 access token). Authentication only — no
  roles. `users` table added in `migrations/postgres/0002_users.sql`.
- `apps/api/src/openlex_api/routers/query.py` implements `POST /query`: requires a valid
  bearer token (`get_current_user`, 401 otherwise). `legal_retrieval`'s `hybrid_search`
  (pgvector cosine + Postgres FTS, fused by reciprocal rank fusion) feeds
  `legal_generation`'s `generate_answer` (grounded, tool-forced, hard-abstains on empty
  retrieval — see the `grounded-answer-contract` skill).
- `apps/api/src/openlex_api/routers/ingest.py` is a deliberate `501`: ingestion runs in the
  worker container only, not via the API (see the router's docstring for why `pipelines/`
  can't be imported from `apps/api`).
- `packages/legal_retrieval/` has `embeddings.py` (BGE asymmetric query/passage embedding,
  `BAAI/bge-small-en-v1.5`) and `search.py` (the hybrid RRF search implementation).
- `packages/legal_generation/` has `generator.py` (grounded answer generation; see
  `ml/prompts/statute_qa_system.txt` for the system prompt).
- `packages/legal_parsing/` has `chunker.py` — `chunk_statute_text` chunks one statute
  section into exactly one chunk (no subsection splitting yet; see ADR-0002 for why and its
  known truncation limitation on long sections); `chunk_case_text` splits case-law opinions
  into multiple paragraph-packed chunks instead, since opinions run far longer than statute
  sections (see ADR-0006).
- `apps/worker/src/openlex_worker/__main__.py` + `cli.py` implement
  `python -m openlex_worker ingest --source {statutes|cases|all}`, so `scripts/compose/ingest.sh` now
  runs for real for both sources. `pipelines/normalization/{statutes,cases}.py` and
  `pipelines/indexing/{statutes,cases}.py` (sharing a common write path in
  `pipelines/indexing/_shared.py`) do the normalize→chunk→embed→upsert work, respecting
  immutable `(source, source_id, version)` rows (no in-place updates — a changed document
  gets a new version).
- `pipelines/ingestion/ny_case_law/seed_cases.json` has real full-text opinions for 3 NY
  Court of Appeals landlord-tenant cases (Park West Management v. Mitchell, Regina
  Metropolitan v. NYS DHCR, Mallory Associates v. Barving Realty) — hand-curated, no live
  fetch (see ADR-0006 for why every free automated case-law text source is either auth-gated
  or bot-blocked).
- `apps/web/` is a working Vite + React + TypeScript + Tailwind chat UI (auth-gated,
  single-conversation, citations + disclaimer displayed per answer) — see ADR-0003.
- `tests/integration/` now has real tests (`test_indexing.py`, `test_indexing_cases.py`,
  `test_normalization.py`, `test_normalization_cases.py`, `test_search.py`) against a real
  Postgres+pgvector — see `scripts/test/test-db.sh` and `tests/integration/README.md` for how to
  run them.
- `tests/evaluation/golden_questions.yaml` + `test_golden_questions.py` now exist: a
  parametrized, real-API golden-question suite marked `evaluation` and excluded from the
  default `uv run pytest` run (real Anthropic calls, needs a running server — see
  `tests/evaluation/README.md`). `scripts/eval/evaluate.sh` runs it for real now.

Before assuming a module/endpoint/script exists, check for it — don't rely on the README's or
this file's description of the target architecture as current fact.

## Commands

```bash
uv sync --all-packages          # install the full workspace (all apps + packages)
uv run ruff check .             # lint
uv run ruff format .            # format
uv run mypy apps packages       # typecheck
uv run pytest                   # run all tests (root pyproject.toml sets testpaths)
uv run --package openlex-api pytest apps/api/tests   # run one package/app's tests only
scripts/test/test-db.sh up            # start db-test (Postgres+pgvector on :5544) for tests/integration
```

Local environments are driven by one **master script** each (`up`/`down`), which chain the
individual scripts and are idempotent. Prefer these over running the steps by hand — the
`local-environment` skill has the full sequence and a symptom→fix troubleshooting matrix, and
the `/bootstrap` command drives either environment end-to-end:

```bash
scripts/compose-master.sh up | down     # docker-compose: bootstrap -> health-wait -> ingest -> seed
scripts/kind-master.sh    up | down     # kind: cluster -> secrets -> ArgoCD -> wait -> ingest -> seed
```

```bash
scripts/compose/bootstrap.sh            # individual steps (behind the compose master):
scripts/compose/ingest.sh all           # run ingestion
scripts/seed/seed-demo-users.sh         # seed the tier-gated demo logins (else /auth/login 401s)
scripts/eval/evaluate.sh                # run the golden-question eval harness (guarded)
scripts/compose/seed-local-db.sh        # re-apply migrations/postgres/*.sql manually
```

Port-forwards are **not** started by the masters (they block). On kind, after `up`, run
`scripts/kind/app-port-forward.sh` and `scripts/kind/observability-port-forward.sh` in separate
terminals, and (re)start them *after* `up` since the pods roll during setup.

- API: http://localhost:8000 (docs at `/docs`)
- Web UI: http://localhost:5173
- Postgres/pgvector: localhost:5432 (user/pass/db: `openlex`/`openlex`/`openlex`)

Each app/package has its own `pyproject.toml`; the root `pyproject.toml` defines the `uv`
workspace plus shared `ruff`/`mypy`/`pytest` config. Add a new dependency to a specific
package with `uv add --package <name> <dependency>`, not by hand-editing lockfiles.

## Architecture

**Data model** (`migrations/postgres/0001_init.sql`, mirrored in
`packages/legal_models/src/legal_models/orm.py`):
- `documents` — one row per source document (statute section or case), keyed by
  `(source, source_id, version)`. `raw_snapshot` (JSONB) holds the immutable raw fetched/seed
  content; `citation` is the human-readable legal citation shown to users (independent of the
  source API's internal IDs — see below).
- `chunks` — chunked passages of a document, each with a 384-dim `embedding` vector (must
  match `EMBEDDING_MODEL_NAME`'s output dimension — currently `BAAI/bge-small-en-v1.5`, see
  `ml/model_cards/bge-small-en-v1.5.md`) and a generated `tsv` column for Postgres full-text
  search. Retrieval is designed to be **hybrid**: pgvector cosine similarity
  (`idx_chunks_embedding`, HNSW) + Postgres FTS (`idx_chunks_tsv`, GIN), combined at query
  time (not yet implemented in `packages/legal_retrieval/`).
- JSON Schema exports of the API-facing shapes live in `schemas/` — `legal_citation` and
  `answer` are generated directly from `legal_models.schemas` (keep in sync when those
  models change); `legal_document` and `retrieval_result` are hand-authored pending real
  pydantic models for them.

**Config** (`packages/shared/src/openlex_shared/config.py`): a single pydantic-settings
`Settings` object loaded from `.env`. Never hardcode config that belongs there (API keys,
model names, DB URL). DB sessions come from `openlex_shared.db.get_session`.

**NY Open Legislation ingestion** (`pipelines/ingestion/ny_legislation/client.py`): the API's
internal `lawId` codes do not match common legal citation abbreviations — e.g. RPAPL is
`lawId "RPA"`, RPL is `"RPP"`, GOL is `"GOB"`. `seed_statutes.json` lists each statute section
to fetch as `{lawId, locationId, citationAbbrev}`; `citationAbbrev` is threaded through
explicitly so the citation shown to users doesn't depend on the API's internal id. Fetches are
throttled sequentially (`_REQUEST_DELAY_SECONDS`) to be polite to the free public API.

Case law has no viable automated full-text source — CourtListener's detail API needs a token,
and its public opinion pages, linked court PDFs, and Justia are all bot-blocked (verified
empirically, see ADR-0006) — so case-law data comes from a hand-curated seed file
(`pipelines/ingestion/ny_case_law/seed_cases.json`) with the full opinion text baked in,
obtained once out-of-band via an authenticated CourtListener API token, not fetched live at
ingestion time.

`pipelines/` modules aren't an installed package — they're plain directories (Python implicit
namespace packages) imported by `apps/worker` at runtime relative to the repo root. Run them
via `uv run` from the repo root (or inside the `worker` container, which mounts the whole repo
at `/repo`), not as a standalone installed dependency.

**Response contract** (`packages/legal_models/src/legal_models/schemas.py`): `QueryResponse`
always includes `citations`, an `abstained` flag (for when retrieval doesn't support an
answer), and the fixed legal `disclaimer` string — these are the shape any future
`/query`-style endpoint must return. See the `grounded-answer-contract` skill.

## Git workflow

Open pull requests against `develop`, not `main` — `main` is the production branch (see
`docs/infrastructure/dev-workflow-and-branching.md`), and `develop` is where day-to-day and
feature work lands first.

**The only branch that may target `main` is `develop`.** Every change flows
`feature/fix branch → develop → main`. Never open or merge a PR from a feature/fix branch (or a
cherry-pick branch) directly into `main`, even to work around something on `develop` that you
don't want promoted yet (e.g. an unrelated in-flight commit). If `develop` isn't in a
promotable state, fix that on `develop` first — do not bypass it. A PR whose base is `main` is
only ever `develop → main`.

## Project skills & agents

`.claude/agents/`, `.claude/skills/`, and `.claude/commands/` hold project-specific context
beyond this file:
- Agents: `backend-implementer` (building out `apps/api`'s routers/`packages/legal_retrieval`/
  `packages/legal_generation`), `data-ingestion` (statute/case-law ingestion pipeline).
- Skills: `openlex-data-model`, `ny-open-legislation-api`, `grounded-answer-contract`, `verify`,
  `local-environment` (bring up / tear down / troubleshoot the compose + kind stacks).
- Commands: `/adr` (scaffold an ADR), `/bootstrap [compose|kind] [up|down]` (drive a local
  environment end-to-end via the `local-environment` skill).

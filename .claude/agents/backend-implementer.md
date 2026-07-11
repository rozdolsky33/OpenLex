---
name: backend-implementer
description: Use when building out OpenLex's FastAPI backend — apps/api's main.py/routers, packages/legal_retrieval, or packages/legal_generation — so new code matches the existing async SQLAlchemy, pydantic-settings, and response-contract conventions already established in the scaffold.
tools: Read, Write, Edit, Bash, Grep, Glob
---

# Backend Implementer

Implements the missing pieces of OpenLex's backend: `apps/api/src/openlex_api/main.py`,
`apps/api/src/openlex_api/routers/`, `packages/legal_retrieval/`,
`packages/legal_generation/`. Read `CLAUDE.md` and
`docs/decisions/0001-monorepo-restructure.md` first for what already exists vs. what's still
missing — don't assume the README's target architecture is already built.

## Conventions to follow

- **Sessions**: use `get_session` from `openlex_shared.db` (async SQLAlchemy `AsyncSession`,
  package `packages/shared`) as a FastAPI dependency — don't create engines/sessions
  elsewhere.
- **Config**: read all secrets/tunables from `openlex_shared.config.settings`
  (pydantic-settings, loaded from `.env`). Never hardcode a model name, API key, or DB URL.
- **Response contract**: any query/answer endpoint must return `legal_models.QueryResponse`
  (`packages/legal_models`) — always populate `citations`, `abstained`, and the fixed
  `disclaimer` (`legal_models.DISCLAIMER`). See the `grounded-answer-contract` skill.
- **Retrieval**: hybrid pgvector (cosine, HNSW) + Postgres FTS (`tsv`, GIN index) over
  `chunks`, joined to `documents`. Lives in `packages/legal_retrieval`. See the
  `openlex-data-model` skill for schema and embedding-dimension constraints.
- **Embeddings**: dimension must match `settings.embedding_model_name` (currently
  `BAAI/bge-small-en-v1.5` → 384-dim, see `ml/model_cards/bge-small-en-v1.5.md`). Changing the
  model requires migrating the `VECTOR(384)` column.
- **New workspace dependency?** Use `uv add --package <app-or-package-name> <dep>` from the
  repo root rather than hand-editing a `pyproject.toml`/`uv.lock`.
- **Statute ingestion already exists** in `pipelines/ingestion/ny_legislation/client.py` —
  see the `ny-open-legislation-api` skill before touching it or adding case-law ingestion
  (that's the `data-ingestion` agent's territory, not this one's).

## Before starting

Check what actually exists — `apps/api/src/openlex_api/routers/`,
`packages/legal_retrieval/`, `packages/legal_generation/`, `packages/legal_parsing/`
currently contain only empty `__init__.py` files. Verify with a quick `find`/`grep` rather
than trusting the README's description of the target architecture.

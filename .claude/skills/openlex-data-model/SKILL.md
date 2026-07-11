---
name: openlex-data-model
description: Use when reading or writing OpenLex's documents/chunks Postgres schema, implementing hybrid retrieval, or choosing/changing the embedding model.
---

# OpenLex Data Model

Two tables (`migrations/postgres/0001_init.sql`, ORM in
`packages/legal_models/src/legal_models/orm.py`):

**`documents`** — one row per source document (statute section or case), unique on
`(source, source_id, version)`. `raw_snapshot` (JSONB) is the immutable raw fetched/seed
content — re-ingesting a changed document should insert a new `version`, not update in place.
`citation` is the human-readable legal citation shown to users (e.g. `"RPAPL § 711"`), kept
independent of the source API's internal ids.

**`chunks`** — chunked passages of a document. `embedding` is `VECTOR(384)` — **must match**
`settings.embedding_model_name`'s output dimension (currently `BAAI/bge-small-en-v1.5`,
384-dim). Changing the embedding model requires a migration to resize this column and
re-embedding every row. `tsv` is a generated `TSVECTOR` column (English) for full-text
search — don't populate it manually, Postgres derives it from `text`.

## Hybrid retrieval

Two indexes exist for combining vector similarity with keyword search at query time:
- `idx_chunks_embedding` — HNSW, `vector_cosine_ops`. Use cosine distance (`<=>`) for
  nearest-neighbor search.
- `idx_chunks_tsv` — GIN over `tsv`. Query with `to_tsquery`/`plainto_tsquery`; score with
  `ts_rank`/`ts_rank_cd`.

Neither retrieval path is implemented yet (`packages/legal_retrieval/` is empty). Combine both (e.g.
reciprocal rank fusion or a weighted score) rather than picking one exclusively — statute text
favors keyword/citation matches, case-law narrative favors semantic similarity.

## Common mistakes

- Writing embeddings with the wrong dimension — always derive it from the configured
  embedding model, don't hardcode `384` in new code.
- Updating a `documents` row in place instead of inserting a new `version` — breaks the
  immutability guarantee `raw_snapshot` is meant to provide.

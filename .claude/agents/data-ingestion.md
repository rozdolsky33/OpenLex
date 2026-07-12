---
name: data-ingestion
description: Use when fetching, parsing, seeding, or debugging OpenLex's source data — NY Open Legislation statutes or case-law seed files — and writing them into the documents/chunks tables.
tools: Read, Write, Edit, Bash, Grep, Glob
---

# Data Ingestion

Owns OpenLex's ingestion pipeline: fetching statute text from the NY Open Legislation API,
loading the hand-curated case-law seed file, chunking, embedding, and writing to Postgres.
Runs as `apps/worker`, calling into `pipelines/ingestion/` and `packages/legal_parsing`.

## What exists

- `pipelines/ingestion/ny_legislation/client.py` — async httpx client, throttled at
  `_REQUEST_DELAY_SECONDS`. See the `ny-open-legislation-api` skill for the
  lawId/citationAbbrev quirk.
- `pipelines/ingestion/ny_legislation/seed_statutes.json` — list of
  `{lawId, locationId, citationAbbrev}` entries to fetch.
- `pipelines/ingestion/ny_case_law/loader.py` + `seed_cases.json` — synchronous local JSON
  load, no live fetch (every free automated case-law text source is auth-gated or
  bot-blocked — see ADR-0006). `seed_cases.json` carries full opinion text baked in, for 3
  hand-curated NY Court of Appeals landlord-tenant cases.
- `apps/worker/src/openlex_worker/__main__.py` — the ingestion entrypoint
  (`python -m openlex_worker ingest --source {statutes|cases|all}`), built per ADR-0005.
- The chunking + embedding step (`packages/legal_parsing`): `chunk_statute_text` (one chunk
  per statute section) and `chunk_case_text` (multi-chunk, paragraph-packed — case opinions
  run far longer, see ADR-0006) split text into `chunks` rows (`chunk_index`,
  `section_label`, `heading_path`, `text`, `token_count`, `embedding`) using
  `settings.embedding_model_name` via `sentence-transformers`. See
  `ml/model_cards/bge-small-en-v1.5.md` for a retrieval-quality gotcha (query instruction
  prefix) that applies when embedding queries vs. chunks.
- `pipelines/indexing/{statutes,cases}.py` share their dedup/versioning/embed-and-insert
  write path via `pipelines/indexing/_shared.py`.

## Extending the case-law seed set

To add another case: find it on CourtListener, confirm the correct sub-opinion (a cluster
can have multiple — lead/dissent/combined), fetch its `plain_text` (or an HTML field
converted to plain text if `plain_text` is empty, common for older opinions) via an
authenticated CourtListener API token, and add an entry to `seed_cases.json` with
`{courtlistener_cluster_id, citation, title, court, decision_date, url, text}`. A
CourtListener token is a one-time seed-curation credential (`COURTLISTENER_API_TOKEN` in
`.env`) — never wire it into `openlex_shared.config.Settings` or any runtime code path; case
ingestion itself has no network dependency.

## Data model rules

- `documents.raw_snapshot` (JSONB) must hold the *immutable* raw fetched/seed payload — never
  mutate it in place; insert a new `version` row instead
  (`UNIQUE(source, source_id, version)`).
- `citation` is the human-facing string (e.g. `"RPAPL § 711"`), independent of the source
  API's internal id — don't derive it directly from `lawId`.
- See the `openlex-data-model` skill for the full schema.

## Import note

`pipelines/` is not an installed workspace package (no `pyproject.toml` of its own) — it's a
plain directory imported by `apps/worker` at runtime via Python's implicit namespace
packages. Run/import it from the repo root (or inside the `worker` container, which mounts
the whole repo), not as a standalone dependency of another package.

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
- `pipelines/ingestion/ny_case_law/` — directory exists with a README only; no code or seed
  data yet.

## What's missing (build here)

- `pipelines/ingestion/ny_case_law/seed_cases.json` — hand-curated NY landlord-tenant case
  law. There's no public scrape source (NY Official Reports blocks automated fetches), so
  this has to be manually curated, not written by a fetch script.
- `apps/worker/src/openlex_worker/__main__.py` — the ingestion entrypoint the README and
  `scripts/ingest.sh` already reference as if it exists (`python -m openlex_worker`).
- The chunking + embedding step (`packages/legal_parsing`): split fetched/seeded text into
  `chunks` rows (`chunk_index`, `section_label`, `heading_path`, `text`, `token_count`,
  `embedding`) using `settings.embedding_model_name` via `sentence-transformers`. See
  `ml/model_cards/bge-small-en-v1.5.md` for a retrieval-quality gotcha (query instruction
  prefix) that applies when embedding queries vs. chunks.

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

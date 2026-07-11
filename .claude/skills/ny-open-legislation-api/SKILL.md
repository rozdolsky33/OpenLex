---
name: ny-open-legislation-api
description: Use when fetching NY statute text from the NY Open Legislation API, adding new statute sections to seed data, or debugging ingestion errors from legislation.nysenate.gov.
---

# NY Open Legislation API

Client lives in `pipelines/ingestion/ny_legislation/client.py`. Base URL and API key come
from `settings.ny_open_leg_base_url` / `settings.ny_open_leg_api_key`
(`openlex_shared.config`).

## Key quirk: lawId ≠ citation abbreviation

The API's internal `lawId` codes don't match the citation abbreviations lawyers use:

| Citation abbrev | API `lawId` |
|---|---|
| RPAPL | `RPA` |
| RPL | `RPP` |
| GOL | `GOB` |

`seed_statutes.json` carries an explicit `citationAbbrev` alongside `lawId`/`locationId` for
exactly this reason — always thread `citationAbbrev` through to the `documents.citation`
field rather than deriving a citation string from `lawId`.

## Request shape

`GET /api/3/laws/{lawId}/{locationId}?key=...` → `{"success": bool, "result": {"lawId",
"locationId", "title", "docType", "activeDate", "text", "parents": [...]}}`. Raise on
`success: false` (see `fetch_law_document`) — don't assume a 200 status means valid data.

## Etiquette

This is a free public API — `fetch_all_seed_statutes` fetches sequentially with a 1s delay
(`_REQUEST_DELAY_SECONDS`) between requests. Keep new fetch code sequential/throttled rather
than firing requests concurrently.

## Adding a new statute section

Append `{"lawId", "citationAbbrev", "locationId"}` to `seed_statutes.json` — no code changes
needed, `load_seed_statutes()` picks it up automatically.

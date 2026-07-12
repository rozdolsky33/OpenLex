# ADR-0006: Case-law ingestion as a static hand-curated seed, multi-chunk chunking, and the v1 case set

## Status
Accepted

## Date
2026-07-12

## Context

`packages/legal_models/src/legal_models/orm.py`'s `Document` model and
`packages/legal_retrieval/src/legal_retrieval/search.py`'s `hybrid_search` (`doc_type`
filter) were already built case-law-ready per ADR-0002 — case law was a pure data-absence
gap, not a schema or retrieval-layer gap. `pipelines/ingestion/ny_case_law/` had only a
README describing the intent ("no public API... hand-curated seed file... not scraped
live") without evidence for *why*, and no code.

Before committing to the hand-curated-seed design, every realistic free automated fetch path
was checked empirically:

- **CourtListener REST v4 detail endpoints** (`/clusters/{id}/`, `/opinions/{id}/`) return
  `401 Unauthorized` without an API token.
- **CourtListener's search endpoint** (`/api/rest/v4/search/?q=...&type=o`) works with no
  auth and returns rich metadata (case name, court, date filed, docket, cluster/opinion ids,
  a `download_url`) — but only a ~300-character snippet of opinion text, not the full
  opinion.
- **CourtListener's public opinion HTML page**
  (`courtlistener.com/opinion/{id}/{slug}/`) returned `HTTP 202` with a 0-byte body via plain
  `curl` — bot-protected, not fetchable that way.
- **The official court decision PDF** linked from CourtListener metadata (e.g. a
  `nycourts.gov` `Decision.pdf` URL) returned `HTTP 403` via plain `curl`.
- **Justia** (`law.justia.com`) also returned `HTTP 403`.

This confirms and extends the existing README's rationale ("NY Official Reports blocks
automated fetches") to every free public case-law source tried, not just NY's official site
specifically. A live-fetch pipeline for case law is not a viable design for this POC; a
static, hand-curated seed file is the only option, mirroring
`pipelines/ingestion/ny_legislation/`'s adapter *pattern* (a `seed_*.json` file drives
ingestion) while diverging on *content* (full text baked in, not fetch instructions) because
there is no runtime source to fetch from.

Separately, `chunk_statute_text`'s v1 design (exactly one `ChunkData` per document, see
ADR-0002 §3) was deliberately scoped to statutes: NY landlord-tenant statute *sections* are
individually narrow. Court of Appeals opinions are not — the consolidated four-case Regina
Metropolitan opinion runs to roughly 34,000 words. Reusing the one-chunk approach for case
law would leave vector search blind to nearly all of a long opinion (not just "truncated," as
with a long statute section, but functionally invisible past the first chunk's embedding),
with no equivalent mitigation to the statute case: full-text search still indexes the whole
`chunks.tsv` regardless of chunk count, but a *single* chunk can only ever contribute one row
to the vector-search candidate list no matter how long the source text is, whereas a
multi-chunk document gets one embedded candidate per chunk.

## Decision

### 1. `seed_cases.json`: static, hand-curated, full text included — no live fetch

`pipelines/ingestion/ny_case_law/seed_cases.json` is a flat list of objects, each carrying
`courtlistener_cluster_id`, `citation`, `title`, `court`, `decision_date`, `url`, and `text`
(the full opinion). `pipelines/ingestion/ny_case_law/loader.py`'s `load_seed_cases()` is a
synchronous local JSON read — no `httpx`, no throttling, no async — a deliberate divergence
from `ny_legislation/client.py`'s shape, since there is nothing to fetch over the network.
`pipelines/normalization/cases.py`'s `normalize_case(raw)` treats the seed entry itself as the
`raw_snapshot` (unlike `normalize_statute`, where `raw_snapshot` is a live API response
distinct from the seed file's fetch instructions), because there is no separate fetched
payload to distinguish it from.

`source` is set to `"courtlistener_seed"` in `normalize_case` — chosen deliberately over a
name implying NY Official Reports (the originally-planned but never-realized source) or
implying a live CourtListener fetch (which doesn't happen at ingestion time). This string
honestly describes actual provenance: hand-curated content, sourced via an authenticated,
one-time CourtListener API fetch, not scraped from NY's official reporter and not fetched
live at runtime.

Full opinion text for the three v1 cases was obtained via a user-supplied CourtListener API
token, used transiently (never committed — see `.env`/`.env.example`'s
`COURTLISTENER_API_TOKEN`, documented as seed-curation-only, not a runtime app setting) to
fetch each case's `plain_text` (or, where that field was empty for older opinions, the best
available HTML field — `html_with_citations`/`html_columbia` — converted to plain text with a
one-time extraction script, not shipped as pipeline code). Each cluster's correct sub-opinion
(a cluster can have multiple opinion documents — lead, dissent, combined) was confirmed via
CourtListener's `sub_opinions` metadata before use; Mallory's dissent (opinion `3576697`) was
identified and excluded in favor of its lead opinion (`3576696`).

### 2. Case-law chunking: paragraph-packed multi-chunk, not one-chunk-per-document

`packages/legal_parsing/src/legal_parsing/chunker.py` gains `chunk_case_text(text, citation,
max_tokens=400)`, in the same module as `chunk_statute_text` (kept together — the package is
small and both share the `ChunkData` dataclass). It splits on blank-line paragraph
boundaries and packs consecutive paragraphs into a chunk until the next paragraph would push
the running word count over `max_tokens`; a single paragraph exceeding `max_tokens` on its
own is kept whole rather than split mid-sentence (the same accepted-for-now truncation
tradeoff `chunk_statute_text` already documents for long statute sections). `max_tokens=400`
is a defensible default, not a measured optimum (same framing ADR-0002 already used for
RRF's constants): word count under-approximates BGE's subword token count for legal prose,
so 400 words leaves headroom under `bge-small-en-v1.5`'s ~512-token `max_seq_length`.

Verified against the real v1 seed data: Park West → 10 chunks (313-word avg), Regina
Metropolitan → 90 chunks (377-word avg), Mallory → 6 chunks (286-word avg) — all comfortably
under the token ceiling, confirming the packing behavior works on real opinion text, not just
synthetic fixtures.

**Alternatives considered:**
- **Fixed-size token-window chunking (ignoring paragraph boundaries)** — rejected for the
  same reason ADR-0002 rejected it for statutes: it cuts mid-sentence, hurting the
  readability of any excerpt shown to a user, for no measured retrieval-quality benefit over
  a boundary-respecting approach.
- **A legal-citation-aware splitter** (splitting on section/paragraph numbering conventions
  specific to Court of Appeals opinions) — explicitly out of scope for this POC; would add
  real parsing complexity for a benefit not yet demonstrated by
  `tests/evaluation/golden_questions.yaml`.
- **Reusing `chunk_statute_text`'s one-chunk-per-document shape for cases too** — rejected:
  this is the problem being solved, not an alternative to it (see Context).

### 3. `pipelines/indexing/_shared.py`: extract, don't duplicate, the write path

`upsert_statute_document`'s dedup-by-`(source, source_id)`/immutable-versioning/embed-and-
insert-chunks logic is extracted into a private `pipelines/indexing/_shared.py:upsert_document`,
called by both `pipelines/indexing/statutes.py:upsert_statute_document` and the new
`pipelines/indexing/cases.py:upsert_case_document` as thin, identically-signed wrappers.
Verified safe against `tests/integration/test_indexing.py` and `conftest.py` (both import
`upsert_statute_document` directly with its current signature) before extracting: generalizing
the `Document(...)` constructor to also pass `court=normalized.get("court")`,
`decision_date=normalized.get("decision_date")` is a no-op for the statute path, since
`normalize_statute`'s output dict never sets those keys and `.get()` returns `None` —
identical to today's implicit default. All 27 pre-existing integration tests plus the new
case-law tests pass unchanged after the extraction. This was judged worth doing (rather than
duplicating ~40 lines of dedup/versioning logic per source) because the extraction is small,
low-risk, and verified safe, per this repo's stated preference (CLAUDE.md) for simplicity
over DRY-at-all-costs *except* where a real, easily-shared bug surface would otherwise be
duplicated — an immutable-versioning bug is exactly that kind of surface.

### 4. The v1 case set

Three NY Court of Appeals decisions, chosen because they map directly onto statutes already
seeded in `seed_statutes.json`, giving the golden-question eval suite real
statute-plus-case-law pairs to test against:

- **Park West Management Corp. v. Mitchell**, 47 N.Y.2d 316 (1979-06-07), CourtListener
  cluster `5683523` — establishes the implied warranty of habitability, directly interpreting
  RPL § 235-b (already seeded).
- **Matter of Regina Metropolitan Co. v. NYS Division of Housing and Community Renewal**
  (consolidated, 4 cases), 35 N.Y.3d 332 (2020-04-02), cluster `4741374` — the controlling
  post-HSTPA authority on rent-overcharge calculation methodology; the most complex/longest
  opinion in the v1 set (~34,000 words), making it the primary stress test for multi-chunk
  chunking. Consolidated case: the `text` field carries the full consolidated opinion as one
  document (not split into 4 `Document` rows) — chunking, not document-splitting, handles its
  length.
- **Mallory Associates, Inc. v. Barving Realty Co.**, 300 N.Y. 297 (1949-12-29), cluster
  `3595591` — establishes landlord-held security deposits as trust funds, directly
  interpreting GOL § 7-103 (already seeded).

Note: a second CourtListener cluster (`9024665`) exists for the Park West case name but is a
later, unrelated U.S. Supreme Court cert-denial entry, not the substantive NY Court of
Appeals opinion — cluster `5683523` is the correct one and is what `seed_cases.json` uses.

## Consequences

- `hybrid_search`/`/query` can now surface real case-law passages: `scripts/ingest.sh cases`
  (or `python -m openlex_worker ingest --source cases`) ingests all three cases with real
  opinion text, producing 106 total chunks (10 + 90 + 6) across the three documents.
- **`chunk_index`/`section_label` semantics now diverge by `doc_type`**: statutes are always
  exactly 1 chunk with `section_label = "§ N"`; cases are N ≥ 1 chunks with
  `section_label = "<citation> (part i of n)"`. Any future code reading `chunks` must not
  assume a 1:1 document:chunk relationship — this was previously safe to assume (only
  statutes existed) and no longer is.
- **`hybrid_search`'s `SearchResult`/`_HYBRID_SEARCH_SQL` select `d.court` but not
  `d.decision_date`**, even though both columns exist and are now populated for case
  documents. This is a real, known gap found during this work, not fixed here — case-law
  search results will show a court but never a decision date until
  `packages/legal_retrieval/search.py` is updated separately. Flagged for whoever next
  touches retrieval-layer case-law display.
- **`pipelines/indexing/_shared.py` couples `statutes.py` and `cases.py`'s write path
  together.** A future third source with genuinely different versioning semantics would need
  to fork out of the shared helper rather than extend it in place — acceptable now with two
  sources sharing identical semantics, revisit if a third source's needs diverge.
- The `apps/worker/src/openlex_worker/cli.py` `if source == "cases": overall_status =
  "skipped"` special case is removed entirely — case ingestion now follows the same
  `"partial_failure" if errors else "ok"` logic as statutes, since it's no longer a
  guaranteed no-op.
- `COURTLISTENER_API_TOKEN` in `.env`/`.env.example` is a one-time seed-curation credential,
  not a runtime application setting — it is never read by `openlex_shared.config.Settings` or
  any code that runs as part of normal ingestion/query serving. Anyone re-curating or
  expanding the seed set in the future needs their own token; it is not wired into the
  running application by design.

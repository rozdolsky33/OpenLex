# ADR-0002: Hybrid retrieval, BGE embedding convention, v1 chunking scope, and server-enforced grounded generation

## Status
Accepted

## Date
2026-07-11

## Context

The first end-to-end slice of OpenLex needed a concrete design for four things the schema and
config already implied but didn't decide:

1. How `packages/legal_retrieval` combines pgvector similarity and Postgres full-text search
   into one ranked result set (the data model was built for hybrid retrieval — see the
   `openlex-data-model` skill — but "hybrid" doesn't specify a fusion algorithm).
2. How queries and passages get embedded with `BAAI/bge-small-en-v1.5`, which is trained
   asymmetrically (see `ml/model_cards/bge-small-en-v1.5.md`).
3. How much a statute section should be split before embedding (`packages/legal_parsing`).
4. How `packages/legal_generation` enforces the answer-only-from-retrieved-context contract
   (`grounded-answer-contract` skill) — whether that enforcement lives in the prompt (trusting
   the model) or in code.

These decisions are implemented now (`packages/legal_retrieval/src/legal_retrieval/search.py`,
`embeddings.py`; `packages/legal_parsing/src/legal_parsing/chunker.py`;
`packages/legal_generation/src/legal_generation/generator.py`) but had no record of the
alternatives considered. This ADR is written after the fact to close that gap — see the
`documentation-and-adrs` skill's guidance on recording architectural decisions even
retroactively. It also retires a dangling reference in `embeddings.py`'s docstring to a
"next implementation milestone" plan that was never committed to the repo; this ADR is now
that record.

## Decision

### 1. Hybrid search fusion: Reciprocal Rank Fusion (RRF)

`hybrid_search()` runs the vector query (pgvector cosine via `idx_chunks_embedding`, HNSW) and
the FTS query (`plainto_tsquery` against `chunks.tsv`, GIN) independently, each capped at
`candidate_limit` (default 50) rows, then fuses by RRF: `score = Σ 1 / (rrf_k + rank)` per
chunk across whichever list(s) it appears in, `rrf_k = 60`. Final results are ordered by fused
score, with `chunk_id` as a deterministic tie-break (repeated identical queries must return a
stable order for golden-question eval reproducibility).

**Alternatives considered:**
- **Weighted linear combination of normalized scores** (e.g. `α·cosine_sim + (1-α)·ts_rank_cd`)
  — rejected because cosine similarity and `ts_rank_cd` are on different, not-directly-
  comparable scales, and picking `α` would need real query data to tune against — RRF only
  needs rank order from each source, not comparable magnitudes, so it works without that
  tuning data.
- **Vector-only retrieval** — rejected because exact statutory phrases and section numbers
  (a landlord-tenant researcher will often search for "RPAPL 711" or an exact clause) are
  something FTS finds reliably and dense embeddings can miss.
- **FTS-only retrieval** — rejected because it fails on paraphrased/conceptual queries that
  don't share vocabulary with the statute text, which is the main reason hybrid retrieval was
  designed into the schema in the first place.

### 2. BGE asymmetric embedding convention

`embed_query()` prepends the instruction prefix `"Represent this sentence for searching
relevant passages: "`; `embed_passage()`/`embed_passages()` do not. This mirrors how
`bge-small-en-v1.5` was trained and contrastively fine-tuned — getting it backwards (or
applying the prefix to both, or neither) measurably degrades retrieval quality per the model
card. This is enforced by having two distinctly-named functions rather than one function with
a boolean flag, so a caller can't accidentally pass `is_query=False` for a query embedding —
the function name itself is the correctness check.

### 3. Chunking v1: one chunk per statute section, no sub-splitting

`chunk_statute_text()` returns exactly one `ChunkData` per document in v1. NY landlord-tenant
statute sections are already narrow (individual numbered sections, not whole articles), so
splitting further on subsection markers (`(a)`, `(b)`, ...) would add parsing complexity with
no retrieval-quality evidence yet that it's needed.

**Known limitation, accepted for v1:** some sections exceed the embedding model's max sequence
length (e.g. RPAPL § 711 is 1000+ words, well over 512 tokens) — `sentence-transformers`
truncates silently, so the *vector* side of retrieval only "sees" a truncated view of long
sections. FTS (`chunks.tsv`) still indexes the full text, so hybrid retrieval isn't blind to
the truncated portion, only degraded on it. `max_tokens` is already an accepted (unused)
parameter on `chunk_statute_text()` so a v2 sub-splitting implementation is a non-breaking
change for callers.

**Alternatives considered:**
- **Fixed-size token-window chunking** — rejected for v1: it would cut mid-sentence at
  arbitrary boundaries, actively hurting readability of citations shown to users, to solve a
  truncation problem that's only confirmed on a minority of sections.
- **Subsection-boundary chunking now** — deferred, not rejected: revisit once
  `tests/evaluation/golden_questions.yaml` (now in place) actually shows retrieval failing on
  multi-subsection questions, rather than guessing at the right split granularity upfront.

### 4. Grounded generation: contract enforced in code, not trusted to the model

`generate_answer()` enforces two rules server-side rather than relying on prompt instructions
alone:
- **Hard abstain on empty/insufficient retrieval.** If fewer than `min_passages` results come
  back, Claude is never called — this is a code branch, not a model decision.
- **Citations are rebuilt from OpenLex's own retrieval metadata**, filtered to the
  `used_chunk_ids` the model's forced tool call (`provide_answer`) claims it used — never from
  model-generated citation text. If the model reports `abstained=False` but the filtered
  citation list is empty (it referenced a chunk id that wasn't actually offered), the response
  is forced to `abstained=True` server-side anyway. `disclaimer` is not a field the tool
  schema exposes at all — it's always `legal_models.schemas.DISCLAIMER`, applied via
  `QueryResponse`'s default, so paraphrasing or dropping it is structurally impossible rather
  than instruction-dependent.

**Alternatives considered:**
- **Trust the model's `abstained` flag and self-reported citations directly** — rejected: a
  single case of the model citing a passage it wasn't given, or answering while forgetting to
  set `abstained`, would silently violate the answer-only-from-retrieved-context guarantee
  that's this project's core safety property (see `grounded-answer-contract` skill). Defense
  in depth here costs a few lines of filtering logic against a contract violation that would
  otherwise be undetectable from the API response alone.
- **Prompt-only enforcement (no tool forcing)** — rejected: free-text answers have no
  structured `used_chunk_ids` to filter against, so server-side citation verification
  wouldn't be possible at all.

## Consequences

- Retrieval quality tuning (RRF's `rrf_k`, `candidate_limit`, chunking granularity) has no
  empirical validation yet — these constants are defensible defaults, not measured optima.
  `tests/evaluation/golden_questions.yaml` now exists and is the evidence source for
  revisiting any of them, but no such tuning pass has happened yet.
- The v1 chunking limitation means very long statute sections have degraded vector recall
  until sub-splitting (v2) lands; FTS is the current mitigation, not a full fix.
- `generate_answer`'s server-side filtering means the Anthropic tool schema and
  `legal_generation`'s parsing logic are now a matched pair — changing `ANSWER_TOOL`'s shape
  (e.g. renaming `used_chunk_ids`) requires updating the parsing code in the same change, or
  the defense-in-depth check silently stops working.
- Case-law retrieval isn't covered by any of this yet — `pipelines/ingestion/ny_case_law/` has
  no seed data, so `hybrid_search`'s `doc_type` filter for `"case"` currently returns nothing.

---
name: grounded-answer-contract
description: Use when implementing or modifying OpenLex's Claude-based answer generation endpoint, so responses keep the answer-only-from-retrieved-context, citation, and legal-disclaimer guarantees.
---

# Grounded Answer Contract

OpenLex answers **only** from retrieved statute/case passages, never from the model's
general legal knowledge — this is a legal-information tool, not legal advice, and the
response shape in `packages/legal_models/src/legal_models/schemas.py` encodes that guarantee.

## Contract (`legal_models.QueryResponse`)

Every answer response must include:
- `answer` — grounded in retrieved chunks only.
- `citations: list[Citation]` — one entry per source passage actually used (`citation`,
  `doc_type`, `title`, `court`, `date`, `url`, `snippet`). Don't cite a chunk the model didn't
  actually use.
- `abstained: bool` — `true` when retrieval didn't surface enough relevant context to answer
  responsibly. The generation prompt must give the model an explicit way to signal "I don't
  have enough to answer" rather than guessing.
- `disclaimer` — always `legal_models.DISCLAIMER` verbatim. Don't let the model paraphrase or
  omit it.

## Prompting guidance

When building the generation prompt (`packages/legal_generation/`, not yet implemented,
templates go in `ml/prompts/`):
- Pass retrieved chunks as the only source of legal content; instruct the model not to
  supplement from its own training knowledge.
- Require the model to ground each claim in a specific retrieved chunk so `citations` can be
  derived from (or verified against) what it actually used.
- Treat low-relevance or empty retrieval results as a signal to set `abstained: true` rather
  than letting the model answer from general knowledge.

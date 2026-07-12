---
name: verify
description: Use before claiming any OpenLex change is complete, fixed, or passing — runs the project's concrete verification gate (lint, types, unit/mock tests, and real-DB integration tests when applicable).
---

# OpenLex Verify

Two tiers. Always run the fast tier. Add the full tier only when the change touches
retrieval, ingestion, migrations, or ORM models.

## Fast tier (seconds, no external services)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy apps packages
uv run pytest -m "not evaluation"
```

This is the same invocation documented in `CLAUDE.md`'s Commands section and enforced by
`.github/workflows/api.yml` / `pipelines.yml` — don't invent a different path list or flag
set here, it will drift from CI.

## Full tier (adds real Postgres+pgvector integration coverage)

Run this in addition to the fast tier when the change touches `packages/legal_retrieval`,
`pipelines/`, `migrations/`, or ORM models in `packages/legal_models`:

```bash
scripts/test-db.sh up
uv run pytest tests/integration -v
```

## Do NOT run as routine verification

`scripts/evaluate.sh` (the `evaluation`-marked golden-question suite) makes real Anthropic API
calls and costs money. It's a pre-merge/CI-triggered check (see `evaluation.yml`'s path-scoped
trigger and `tests/evaluation/README.md`), not something to run on every change.

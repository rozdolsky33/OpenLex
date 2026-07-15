# Contributing to OpenLex

This is a solo-maintained POC, but this file exists so the local dev loop survives context
resets — for future-you and for any Claude Code session picking the project up cold. See
`README.md` for prerequisites/setup and `CLAUDE.md` for architecture and current build state.

## Local dev loop

```bash
scripts/compose/bootstrap.sh              # first-time setup: .env, uv sync, docker compose up

# working on retrieval / ingestion / migrations / ORM models?
scripts/test/test-db.sh up             # start the ephemeral db-test Postgres+pgvector (:5544)

# ... edit ...

# verify (see .claude/skills/verify for the fast-vs-full-vs-never breakdown)
uv run ruff check .
uv run ruff format --check .
uv run mypy apps packages
uv run pytest -m "not evaluation"
```

Claude Code sessions in this repo auto-run `ruff format`/`ruff check --fix` on edited `.py`
files via the `PostToolUse` hook in `.claude/settings.json` — but that only fixes files Claude
edits, not manual edits or edits from other tools. `scripts/compose/bootstrap.sh` also installs a git
pre-commit hook (`.pre-commit-config.yaml`, via `pre-commit install`) that runs the same
ruff/mypy checks plus a gitleaks secret scan on every commit, regardless of what edited the
files — run `pre-commit run --all-files` manually if you skipped bootstrap or need to re-check
everything at once. See `docs/decisions/0005-local-dev-process-hardening.md` for why both
layers exist (they cover different edit paths, not the same one twice).

## Before pushing

- [ ] `uv run ruff check .` && `uv run ruff format --check .`
- [ ] `uv run mypy apps packages`
- [ ] `uv run pytest -m "not evaluation"`
- [ ] `uv run pytest tests/integration -v` (with `scripts/test/test-db.sh up`) if you touched
      `packages/legal_retrieval`, `pipelines/`, `migrations/`, or ORM models in
      `packages/legal_models`
- [ ] A new ADR in `docs/decisions/` (or `/adr` in Claude Code) if this is an architectural
      decision, not just an implementation detail

Do **not** run `scripts/eval/evaluate.sh` (the golden-question legal-accuracy suite) as part of
routine verification — it makes real Anthropic API calls and costs money. It runs
automatically in CI on relevant PRs (`evaluation.yml`) and via manual dispatch.

## Branching and PRs

Trunk-based: short-lived feature branches off `main`, merged via PR with a real (non-squash)
merge commit. Branch names should describe the feature/ADR they implement. CI
(`.github/workflows/*.yml`) is path-scoped — a PR only triggers the workflows relevant to the
paths it touches; the PR template has a line to note which ones you expect to run.

## Architecture decisions

Non-trivial architectural choices get an ADR in `docs/decisions/`, following the existing
`0001`–`0004` numbering and `Status`/`Date`/`Context`/`Decision`/`Consequences` structure. Use
`/adr` in Claude Code to scaffold a new one.

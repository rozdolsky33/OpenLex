# ADR-0004: Golden-question evaluation report, published to GitHub Pages

## Status
Accepted

## Date
2026-07-11

## Context

The `golden-questions` CI job (`.github/workflows/evaluation.yml`) already runs the real
questions in `tests/evaluation/golden_questions.yaml` against a live stack on every matching
PR, but only ever produced ephemeral terminal output — a pass/fail snapshot for that one run,
discarded once the job finished. There was no way to see a regression as a trend, see *why* a
question failed (actual vs. expected citations/answer) without re-reading CI logs, or notice
that a statute's live text changed after the golden answer it's graded against was ingested.

Two of those signals are specific to decisions this project already made, not generic
reporting:

- **Haiku-vs-Sonnet divergence** — CI runs Haiku for cost (see the `ANTHROPIC_MODEL` override
  in `evaluation.yml`'s `.env` write), while production runs Sonnet
  (`Settings.anthropic_model`'s default, `packages/shared/src/openlex_shared/config.py`).
  Watching where the two models' answers actually diverge is watching the risk of that
  cost/accuracy tradeoff, not a generic model comparison.
- **Statute freshness** — NY law text can change after ingestion; a golden answer's
  correctness is only as good as the statute snapshot it was graded against
  (`documents.raw_snapshot`, immutable per `(source, source_id, version)` — see
  ADR-0001/ADR-0002's data model).

GitHub Pages was enabled on the repo with the modern `build_type: "workflow"` deployment
source (`https://rozdolsky33.github.io/OpenLex/`) — no branch-based Pages config, no static
site generator dependency, `actions/deploy-pages` deploys straight from an uploaded artifact.

## Decision

### 1. Structured per-question results via pytest's Stash API, not a report plugin

`tests/evaluation/conftest.py` exposes an `eval_result` fixture (a plain dict); each
parametrized case in `test_golden_questions.py` stashes actual response data (citations,
answer, abstained) into it **before its assertions run**, so a *failing* test still records
what it actually got, not just that it failed — this is what makes "actual vs. expected" useful
for exactly the rows that matter most. `pytest_runtest_makereport` (hookwrapper) reads the
stash and `pytest_sessionfinish` writes `{run_metadata, results: [...]}` to
`EVAL_RESULTS_PATH` (default `eval-results.json`).

**Alternative considered:**
- **`pytest-json-report`** — an existing dependency would have been preferable in principle,
  but its schema doesn't carry evaluation-specific fields (expected citations, abstain flag)
  without a custom hook anyway, so it wouldn't have avoided writing one. A bespoke ~30-line
  hook gives full schema control at no extra dependency cost.

### 2. Hybrid trigger: PR runs stay cheap, only a push to `main` runs the full comparison

```yaml
on:
  pull_request:
    paths: [...]        # unchanged
  push:
    branches: [main]
    paths: [...]         # same filter
```

`pull_request` events keep today's single-model (Haiku) pass, unchanged cost and behavior.
`push` events to `main` run an extended sequence: a statute-freshness check, the existing Haiku
pass, a **drift guard** (see §4), a second `.env` write switching `ANTHROPIC_MODEL` to
`claude-sonnet-4-5`, `docker compose up -d --force-recreate --no-deps api`, a second
`/healthz` wait, and a second eval pass — then uploads all three result files as a single
workflow artifact for the publish job.

**Why a recreate, not a restart:** `Settings` (`openlex_shared/config.py`) is a module-level
singleton built once at container process start from `env_file: .env`. A `docker compose
restart` reuses the already-running process's already-baked env and would silently keep
answering with Haiku; `--force-recreate` tears down and starts a fresh process that re-reads
`.env`. `--no-deps` leaves `db`/`worker` untouched (the worker never calls Claude).

**Alternative considered:**
- **Run the dual-model comparison on every PR** — gives per-PR divergence signal immediately,
  but roughly doubles real Anthropic spend (21 extra Sonnet calls, meaningfully more expensive
  per-token than Haiku) on every PR touching the path filters, not just merges. Rejected:
  `main`-only pushes are inherently less frequent than PRs, so gating there keeps the
  expensive path rare without losing the comparison entirely.

### 3. Statute freshness check runs before any Claude spend

`scripts/check_statute_freshness.py` (new — the first non-bash file in `scripts/`) re-fetches
each of the 18 seeded sections via the existing `fetch_law_document` client
(`pipelines/ingestion/ny_legislation/client.py`, same `_REQUEST_DELAY_SECONDS` throttle
already used by ingestion) and compares live `activeDate` against the stored document's. It
runs immediately after ingestion, before either Claude pass, so a transient NY Open
Legislation API hiccup doesn't burn Claude budget first. The step is `continue-on-error: true`
in the workflow; the report renders an explicit "freshness check unavailable this run" state
rather than failing CI over a third-party API blip (mirrors
`pipelines/indexing/statutes.py::upsert_all_seed_statutes`'s existing per-document error
handling — one bad fetch doesn't abort the batch).

### 4. Drift guard on the production model default

One step before the `.env` rewrite asserts
`Settings.model_fields["anthropic_model"].default == "claude-sonnet-4-5"` and fails loudly if
not. Without this, a future change to the production default would silently mislabel the
"Sonnet comparison" pass as something it no longer is, and the divergence report would compare
against the wrong baseline without any signal that it happened.

### 5. Divergence flag: abstain-mismatch or disjoint citations, not answer-text diff

`scripts/generate_eval_report.py`'s `_diverges()` flags a question when the two models'
`actual_abstained` differ, or their citation sets share no overlap at all. It deliberately does
**not** flag on answer-text differences alone — Haiku and Sonnet phrase things at least
slightly differently even when citing identically, so text-diff-as-divergence would flag
nearly every question and defeat the point of the signal. Answer text is still shown
side-by-side in the report for human judgment; it just doesn't set the flag.

### 6. `gh-pages` branch as a git-native history store, not how Pages serves the site

`actions/deploy-pages` deploys straight from an uploaded artifact to GitHub's Pages CDN
regardless of any branch content — this project's `build_type: "workflow"` Pages
configuration needs no branch at all for serving. `gh-pages` is used here purely as our own
append-only data store for `history.ndjson` (one JSON object per line — newline-delimited
specifically because line-appends are more merge-friendly than editing a growing JSON array's
closing bracket), checked out, appended to, and pushed by the `publish-eval-report` job's own
steps, independent of the actual Pages deployment mechanism.

**Alternative considered:**
- **Store history as a workflow artifact only** — no new branch/permissions, but artifacts
  expire (90-day default) and aren't trivially diffable/appendable across runs the way a
  tracked file is. Rejected since the trend view is the whole point of persisting anything.

### 7. New `publish-eval-report` job, gated to `main`-push only

`needs: golden-questions`, `if: github.event_name == 'push' && github.ref ==
'refs/heads/main'`. New permissions on this job only: `contents: write` (to push
`history.ndjson`), `pages: write`, `id-token: write` (both required by
`actions/deploy-pages@v4`). `concurrency: {group: eval-report-publish, cancel-in-progress:
false}` queues rather than cancels overlapping runs — the primary defense against two
close-together `main`-push runs racing on the `gh-pages` append; given the narrow path filter,
overlap is rare enough that queuing costs nothing but a short wait.

## Consequences

- **PR runs: no change** — still one Haiku pass, today's cost and ~5-6 minute runtime exactly.
- **`main`-push runs only**: roughly 42 real Claude calls (21 Haiku + 21 Sonnet, and Sonnet is
  more expensive per-token on top of the call-count doubling) plus 18 more NY Open Legislation
  calls for freshness, on top of the 18 already made during ingestion. `golden-questions`
  grows from ~5-6 minutes to roughly 10-14 minutes on `main`-push (a second embedding-model
  reload cycle after the container recreate is the biggest new chunk); `publish-eval-report`
  adds a separate ~1-3 minute job. These are estimates to be calibrated against real
  `main`-push runs, not measured numbers.
- No new secrets — reuses `ANTHROPIC_API_KEY`/`NY_OPEN_LEG_API_KEY` and the workflow's
  `GITHUB_TOKEN` (with the new `permissions:` grants on `publish-eval-report` only).
- `jinja2` added to the root `pyproject.toml` dev group for `scripts/generate_eval_report.py`'s
  template rendering — the first templating dependency in the repo, kept intentionally small
  (a self-contained template, no external CDN/JS in the published page) rather than reaching
  for a full static-site generator or coupling to `apps/web`'s separate toolchain.
- The published report's historical trend and freshness sections are only as current as the
  last successful `main`-push run of `publish-eval-report` — a failed or skipped run doesn't
  roll back what's already published, so the dashboard can lag behind `main` if that job breaks
  and isn't noticed.
- Case-law retrieval still isn't covered (ADR-0002's open item, restated in ADR-0003) — the
  golden-question set and this report are statute-only until case-law ingestion exists.

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

### 2. Hybrid trigger: PR runs stay cheap and automatic, the full comparison is manual

```yaml
on:
  pull_request:
    paths: [...]        # unchanged
  workflow_dispatch: {}
```

`pull_request` events keep today's single-model (Haiku) pass, unchanged cost and behavior,
firing automatically on every matching PR. The full comparison — statute-freshness check, the
existing Haiku pass, a **drift guard** (see §4), a second `.env` write switching
`ANTHROPIC_MODEL` to `claude-sonnet-4-5`, `docker compose up -d --force-recreate --no-deps
api`, a second `/healthz` wait, a second eval pass, and the artifact upload feeding the publish
job — only runs on `workflow_dispatch` (Actions tab > evaluation > Run workflow, or `gh
workflow run evaluation.yml --ref main`). This was originally designed as an automatic
`push: branches: [main]` trigger, but changed to manual-only shortly after the first rollout:
during active development, merges to `main` are frequent enough that automatic firing would
have made the 2x-cost dual-model pass a routine per-merge expense rather than a deliberate,
occasional check. Manual-for-now is explicitly a cost-control choice for the current
development phase, not a permanent judgment that this shouldn't ever run automatically — it's
easy to revisit once merge frequency and real per-run cost are both better known.

**Why a recreate, not a restart:** `Settings` (`openlex_shared/config.py`) is a module-level
singleton built once at container process start from `env_file: .env`. A `docker compose
restart` reuses the already-running process's already-baked env and would silently keep
answering with Haiku; `--force-recreate` tears down and starts a fresh process that re-reads
`.env`. `--no-deps` leaves `db`/`worker` untouched (the worker never calls Claude).

**Alternatives considered:**
- **Run the dual-model comparison on every PR** — gives per-PR divergence signal immediately,
  but roughly doubles real Anthropic spend (21 extra Sonnet calls, meaningfully more expensive
  per-token than Haiku) on every PR touching the path filters, not just merges. Rejected for
  the same cost reason as below, more so.
- **Automatic on push to `main`** — the original design (see above): less manual toil than
  `workflow_dispatch`, but ties real spend directly to merge frequency during a phase where
  that frequency is still high and unpredictable. Rejected for now in favor of an explicit,
  human-initiated trigger; may be revisited once `main`-push frequency settles down.

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

### 7. New `publish-eval-report` job, gated to a manual dispatch against `main`

`needs: golden-questions`, `if: github.event_name == 'workflow_dispatch' && github.ref ==
'refs/heads/main'` — a manual run dispatched against a branch other than `main` still exercises
the dual-model eval (useful for testing before merge) but skips publishing. New permissions on
this job only: `contents: write` (to push `history.ndjson`), `pages: write`, `id-token: write`
(both required by `actions/deploy-pages@v4`). `concurrency: {group: eval-report-publish,
cancel-in-progress: false}` queues rather than cancels overlapping runs — the primary defense
against two close-together manual runs racing on the `gh-pages` append.

## Consequences

- **PR runs: no change** — still one Haiku pass, today's cost and ~5-6 minute runtime exactly,
  firing automatically as before.
- **Manual `workflow_dispatch` runs only** (no longer automatic on push to `main` — see §2):
  roughly 42 real Claude calls (21 Haiku + 21 Sonnet, and Sonnet is more expensive per-token on
  top of the call-count doubling) plus 18 more NY Open Legislation calls for freshness, on top
  of the 18 already made during ingestion. `golden-questions` grows from ~5-6 minutes to
  roughly 10-14 minutes on a manual run (a second embedding-model reload cycle after the
  container recreate is the biggest new chunk); `publish-eval-report` adds a separate ~1-3
  minute job. These are estimates to be calibrated against real runs, not measured numbers.
  Because the trigger is manual, this cost is opt-in per run rather than tied to merge
  frequency.
- No new secrets — reuses `ANTHROPIC_API_KEY`/`NY_OPEN_LEG_API_KEY` and the workflow's
  `GITHUB_TOKEN` (with the new `permissions:` grants on `publish-eval-report` only).
- `jinja2` added to the root `pyproject.toml` dev group for `scripts/generate_eval_report.py`'s
  template rendering — the first templating dependency in the repo, kept intentionally small
  (a self-contained template, no external CDN/JS in the published page) rather than reaching
  for a full static-site generator or coupling to `apps/web`'s separate toolchain.
- The published report's historical trend and freshness sections are only as current as the
  last successful manually-dispatched run of `publish-eval-report` — with an automatic trigger
  removed (§2), the dashboard is now expected to lag behind `main` between manual runs, not
  just when something breaks; whoever wants a fresh report needs to remember to trigger one.
- Case-law retrieval still isn't covered (ADR-0002's open item, restated in ADR-0003) — the
  golden-question set and this report are statute-only until case-law ingestion exists.

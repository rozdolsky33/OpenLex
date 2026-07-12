# ADR-0005: Local dev-process hardening — pre-commit gates, incremental mypy strictness, and closing the worker test gap

## Status
Proposed

## Date
2026-07-11

## Context

A process audit of OpenLex's engineering practices (comparing CI in `.github/workflows/`,
git/PR hygiene, testing coverage, and Claude Code leverage against current industry-standard
practice) found the repo to be a well-run solo POC overall, but with one structural weakness:
**nothing gated a commit or push locally** — every lint/type/format problem was caught only
after pushing, in CI. A first implementation pass closed the cheap, zero-risk gaps: a Claude
Code `PostToolUse` hook (`.claude/settings.json` + `.claude/hooks/format-python.sh`) that
auto-runs `ruff format`/`ruff check --fix` on any file Claude Code edits, a project-specific
`verify` skill, an `/adr` command (used to write this record), `CONTRIBUTING.md` +
`.github/PULL_REQUEST_TEMPLATE.md`, `pytest-cov` reporting, and branch protection on `main`
requiring `security.yml`'s two unconditional checks.

That pass deliberately deferred three things as needing judgment rather than a blind
file-add: a local pre-commit gate (the Claude Code hook only fires for edits *Claude Code
itself* makes, not manual edits or edits from other tools), incremental mypy strict-mode
adoption, and — once coverage reporting was live — actually looking at what it reported.
Doing that surfaced a real problem with the reporting itself: `[tool.coverage.run] source =
["apps", "packages"]` silently *dropped* `apps/worker` from the coverage table entirely,
rather than showing it at 0%, because it has no test suite and coverage.py's
unexecuted-file discovery doesn't reliably recurse into sibling src-layout packages sharing
one parent directory. That's exactly the failure mode coverage reporting was added to
prevent — a real gap hiding behind a report that looked complete.

## Decision

1. **Fixed the coverage blind spot.** `[tool.coverage.run] source` now lists each uv
   workspace member's `src/` directory explicitly (`apps/api/src`, `apps/worker/src`,
   `packages/legal_generation/src`, etc.) instead of the bare `apps`/`packages` parents.
   Verified empirically: `apps/worker` vanished from the report under the bare-directory
   config and appeared correctly at 0% once scoped precisely.

2. **Closed the gap that surfaced.** Wrote real unit tests for
   `apps/worker/src/openlex_worker/{cli.py,__main__.py}` (0% → 96–97%), using the same
   `unittest.mock.AsyncMock`/patch-at-call-site convention already established in
   `apps/api/tests`. Extracted a `main()` function out of `__main__.py`'s
   `if __name__ == "__main__":` guard so the CLI dispatch logic (ingest vs. heartbeat
   fallback, exit codes) is directly unit-testable without a subprocess.

3. **Added `.pre-commit-config.yaml`**: local `ruff check --fix` / `ruff format` / `mypy
   apps packages` hooks (the exact invocation already documented in `CLAUDE.md` and enforced
   in `.github/workflows/api.yml`/`pipelines.yml`) plus `gitleaks` pinned at `v8.30.1`.
   Wired into first-time setup via `uv run pre-commit install` in `scripts/bootstrap.sh`.
   Local hooks auto-fix; CI stays fail-only — intentional asymmetry, not drift, documented
   as a comment in the config file itself.

4. **Rolled out mypy strict mode incrementally**, starting with the two smallest,
   most-depended-on packages (`openlex_shared`, `legal_models`) via
   `[[tool.mypy.overrides]]`, per the "smallest and most-imported first" reasoning from the
   original audit. Both passed clean with zero code changes required.

5. **Found and worked around a real mypy 2.2.0 bug** in the process: setting `strict = true`
   as the override's flag (the meta-flag form) leaked strict-mode errors into unrelated,
   *unmatched* modules across the entire `apps packages` invocation — 26 errors in 10 files
   (test files, `pipelines/ingestion/ny_legislation/client.py`,
   `legal_retrieval/embeddings.py`) that don't match `openlex_shared.*`/`legal_models.*` at
   all. Reproduced with a clean `.mypy_cache` to rule out a stale-cache artifact. Fixed by
   using the equivalent set of explicit granular flags
   (`disallow_untyped_defs`, `disallow_incomplete_defs`, `disallow_any_generics`,
   `disallow_untyped_decorators`, `check_untyped_defs`, `warn_return_any`,
   `no_implicit_optional`) instead of the `strict` meta-flag, which scope correctly.

## Consequences

- A change is now caught at three points before it can regress `main`: the Claude Code hook
  (edit-time), pre-commit (any commit, including manual edits), and CI (push/PR) — rather
  than relying on the last one alone.
- The coverage gap that made `apps/worker`'s complete absence of tests invisible is now
  structurally harder to reintroduce silently: a new workspace member needs a line added to
  `[tool.coverage.run] source`, called out by a comment at that config site.
- `apps/worker`'s ingestion-CLI dispatch logic — previously exercised only manually via
  `scripts/ingest.sh` — is now directly covered (96–97%), including the `--source`/`--force`
  branches, the partial-failure/skip status logic, and the heartbeat fallback for
  `docker compose up worker` with no subcommand.
- Local `pre-commit run --all-files` adds a few seconds per commit (the `mypy` hook
  type-checks the whole workspace, not just changed files, to match CI's invocation exactly
  and avoid the ambiguous-module-name problem `explicit_package_bases` already documents).
  Acceptable at current codebase size; revisit (scope to changed packages, or move mypy to a
  CI-only stage) if it becomes real friction as the codebase grows.
- **Anyone touching `[[tool.mypy.overrides]]` in the future should not use the `strict = true`
  meta-flag** until the mypy 2.2.0 leak above is confirmed fixed upstream — use the explicit
  flag list instead.
- Next mypy-strict candidates, in order, each as its own follow-up once the previous scope is
  clean: `legal_parsing` (smallest remaining), then `legal_retrieval`/`legal_generation`/
  `apps.api`/`apps.worker` (largest, most churn, last).
- Still deliberately not done, unchanged from the original audit, with reasoning:
  - **`CODEOWNERS`** — a no-op for a single-owner repo; add when a second contributor joins.
  - **A `frontend-implementer` agent** (mirroring `backend-implementer`) — `apps/web` still
    has no real code or established conventions to encode; add once it does.
  - **A `/test-db` slash command** — `scripts/test-db.sh up && pytest tests/integration -v`
    is already a one-liner; doesn't clear the "genuinely non-trivial" bar a command should.
  - **A hard `--cov-fail-under` threshold** — `packages/shared/tests/` is still empty (though
    `config.py`/`db.py` get indirect coverage via other packages' tests) and `apps/web` has
    no Python code at all; a hard number now would be trivially gameable or block unrelated
    PRs. Revisit once `packages/shared` has direct tests of its own.

# GA Readiness Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan phase-by-phase. Phases
> 1-2 are specified at file/diff level and are ready to execute now. Phases 3-6 are specified
> at task level only — write a follow-up detailed plan (superpowers:writing-plans) for each
> phase immediately before starting it, per superpowers:incremental-implementation (don't
> front-load implementation detail for work that's still weeks out and may shift).

**Goal:** Take OpenLex from its current ~50% "demo-grade" state (assessed 2026-07-12) to GA:
public-facing, safe under abuse/scale, observable in production, legally compliant, and backed
by a legal corpus wide enough to be useful rather than a toy.

**Source assessment:** see the GA-readiness audit in-conversation (2026-07-12) — data
coverage, security, testing, CI/CD, observability, infra, known gaps, feature completeness,
and legal/compliance were all scored. This roadmap addresses every 🔴 blocker and 🟡 partial
item from that audit.

**Companion doc:** `docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md` is the flat,
checkbox-only tracking sheet — check items off there as PRs land; this file has the detail
and reasoning behind each item.

## Global Constraints

- Every new/changed Python file passes `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy apps packages` and its package's tests before being considered done (see
  `.claude/skills/verify`).
- Every phase must leave `main` deployable — no phase depends on a later phase's code existing
  first (see per-phase "Dependencies").
- Don't gold-plate: each phase closes exactly the gap the audit identified, nothing more (e.g.
  rate limiting doesn't need a Redis-backed distributed limiter until there's a second API
  replica — see Phase 1's Open Question).

---

## Phase 0 — Fast, low-risk prep (S, no dependencies)

Small fixes that unblock accurate CI signal before bigger phases land on top of it.

### Task 0.1: Fix `pipelines.yml`'s stale "no worker tests" comment and actually run them

**Files:** `.github/workflows/pipelines.yml`

`apps/worker/tests` exists (2 files) but the workflow's comment claims it doesn't and the test
step never includes it. Add `apps/worker/tests` to the `pytest` invocation's path list; delete
the stale comment.

**Acceptance criteria:**
- [ ] `pipelines.yml`'s `pytest` step includes `apps/worker/tests`
- [ ] Stale "apps/worker/tests doesn't exist yet" comment removed
- [ ] CI run on a PR touching `apps/worker` shows worker tests actually executing

**Verification:** open a PR touching `apps/worker/`, confirm the Actions log shows worker test
collection > 0.

**Estimated scope:** XS (1 file)

### Task 0.2: Make `cors_allow_origins` deployment-explicit

**Files:** `infra/kubernetes/overlays/eks-demo/*`, `docs/infrastructure/README.md`

`packages/shared/src/openlex_shared/config.py:17` defaults `cors_allow_origins` to
`["http://localhost:5173"]`. It's already overridable via env var — the gap is nothing sets it
for the `eks-demo` overlay, so a real deployment silently keeps the dev-only default. Add
`CORS_ALLOW_ORIGINS` to the `eks-demo` overlay's ExternalSecret/env and document that every
deployment target must set it explicitly to its real frontend origin(s).

**Acceptance criteria:**
- [ ] `eks-demo` overlay sets `CORS_ALLOW_ORIGINS` to the real deployed web origin, not localhost
- [ ] `docs/infrastructure/README.md` states this is a required per-environment value, not a default to trust

**Estimated scope:** S (2 files)

### Checkpoint: Phase 0
- [ ] CI green on both changes
- [ ] No behavior change for local dev (`docker compose up` still works unchanged)

---

## Phase 1 — SaaS tier quotas (blocks Anthropic-cost abuse) 🔴 ✅ implemented 2026-07-12

**Superseded design:** this phase originally planned a flat 20/min-per-user `slowapi` limiter
on `/query`. The user reshaped it into a real SaaS-tier model instead — three fixed demo users
(Silver/Gold/Platinum), each with a distinct total request quota (15/50/100) on a 4-hour
rolling window, enforced server-side and shown in the UI. Full design, data model, and task
breakdown: `.claude/plans/also-add-to-the-lexical-lollipop.md` (approved and implemented
2026-07-12). Summary:

- `users.tier`/`request_count`/`period_started_at` columns (`migrations/postgres/0004_user_tiers.sql`)
- `apps/api/src/openlex_api/quota.py` — atomic `UPDATE...WHERE...RETURNING` quota check/consume,
  race-safe under concurrent requests (proven against real Postgres, not just mocked)
- `POST /query` returns `429` with `{tier, limit, reset_at}` once a user's window is exhausted;
  every successful response carries `usage` so the frontend tracks it live
  (`apps/web/src/components/TierBadge.tsx`)
- `POST /auth/register` disabled (403) — only the three seeded demo users can log in
  (`apps/api/src/openlex_api/seed_demo_users.py`, `scripts/seed-demo-users.sh`)
- Tier-labeled Prometheus counters (`openlex_query_requests_total`,
  `openlex_query_quota_exceeded_total`) and structured per-request logs — this is also the
  observability showcase referenced in Phase 3 below, pulled forward here since it's the same
  code path

`/auth/login`'s own brute-force protection (a separate, tier-independent rate limiter) was
**not** part of this pass — that gap from the original Phase 1 design is still open. Revisit as
a small standalone follow-up (still `slowapi`, `5/minute` per IP on `/auth/login` only) rather
than reopening the tier-quota design.

---

## Phase 2 — Conversation authorization (cross-tenant data exposure) 🔴 ✅ implemented 2026-07-12

**Why:** `apps/api/src/openlex_api/routers/query.py`'s own comment admits any authenticated
user holding a `conversation_id` (a UUID, easy to guess-adjacent if sequential access patterns
leak, and trivially shareable) can read/continue someone else's conversation. This is a real
data-exposure bug for a product whose conversations may contain a user's personal legal
situation.

**Architecture decision:** Add `user_id` to `conversations`, scope every load/list by the
authenticated caller's `user.id`, and treat "conversation exists but belongs to someone else"
the same as "conversation doesn't exist" (404, not 403 — don't leak existence).

### Task 2.1: Migration — add `conversations.user_id`

**Files:** Create `migrations/postgres/0005_conversation_ownership.sql` (renumbered from the
original `0004_...` — `0004_user_tiers.sql` claimed that slot when Phase 1 was implemented
first; check `migrations/postgres/` for the actual next-free number at implementation time)

```sql
ALTER TABLE conversations
    ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations (user_id);
```

Nullable at the DB level (existing rows have no owner) but the application layer (Task 2.3)
must always set it for new conversations and must never load a `NULL`-owner conversation for
any user — treat legacy unowned rows as orphaned/inaccessible, not "assign on first access"
(simpler, and there's no real user data at this stage to migrate).

**Acceptance criteria:**
- [ ] Migration applies cleanly via `scripts/seed-local-db.sh` against a fresh DB
- [ ] `docker-compose.yml`'s `db`/`db-test` services still boot clean with the new file present

**Estimated scope:** XS (1 file)

### Task 2.2: `Conversation` ORM model + `user_id` field

**Files:** `packages/legal_models/src/legal_models/orm.py`

Add `user_id: Mapped[uuid.UUID | None]` to `Conversation`, matching the migration.

**Acceptance criteria:**
- [ ] `uv run mypy packages/legal_models` clean
- [ ] Existing `packages/legal_models/tests` pass unmodified

**Estimated scope:** XS (1 file)

### Task 2.3: Thread `user_id` through `handle_query_turn` and scope conversation loads

**Files:**
- `packages/legal_generation/src/legal_generation/conversation.py`
- `apps/api/src/openlex_api/routers/query.py`

`handle_query_turn` gains a required `user_id: uuid.UUID` parameter. `_load_conversation`:
- On create (`conversation_id is None`): sets `Conversation(user_id=user_id)`
- On continue: loads by `id == conversation_uuid AND user_id == user_id` (not `session.get`,
  which can't filter) — a mismatch (wrong owner or nonexistent id) raises the existing
  `ConversationNotFound`, so `query.py` keeps returning 404, not a new 403 (no existence leak).

`query.py`'s `query()` handler passes `user_id=user.id` (already has `user` from
`get_current_user`) and drop the now-inaccurate comment about conversations not being scoped.

**Acceptance criteria:**
- [ ] User A cannot continue User B's `conversation_id` — gets 404, identical to a nonexistent id
- [ ] User A can still continue their own conversation across multiple turns (regression check)
- [ ] Comment in `query.py` about unscoped conversations is removed/corrected

**Verification:** new test in `apps/api/tests/test_query.py` (or new file) — two registered
users, user A starts a conversation, user B attempts to continue it with A's `conversation_id`,
assert 404.

**Files likely touched:** `packages/legal_generation/src/legal_generation/conversation.py`, `apps/api/src/openlex_api/routers/query.py`, `apps/api/tests/test_query.py`, `packages/legal_generation/tests/test_conversation.py`

**Estimated scope:** M (4 files)

### Checkpoint: Phase 2
- [ ] `uv run mypy apps packages` clean
- [ ] `uv run --package openlex-api pytest apps/api/tests packages -v` green
- [ ] `tests/integration/test_conversations.py` updated/passing against real Postgres (`scripts/test-db.sh up`) — this is exactly the kind of cross-row bug integration tests exist to catch
- [ ] Manual check via `/docs`: register two users, confirm cross-user continue returns 404

---

## Phase 3 — Production observability 🔴 (partially covered by Phase 1)

**Why:** Right now the only production signal beyond Phase 1's tier metrics is `/healthz`. No
general request logs, no error tracking, no request-latency metrics — most incidents are still
diagnosed by guessing. `infra/monitoring/{prometheus,grafana}` are empty placeholder READMEs.

**Already done (via Phase 1, not this phase):** `GET /metrics` exists
(`apps/api/src/openlex_api/main.py`) and exposes two tier-labeled `prometheus_client` counters
(`openlex_query_requests_total`, `openlex_query_quota_exceeded_total`) plus a structured JSON
log line per `/query` call (`openlex_api.quota._log_quota_event`). Tier is already a
first-class metric/log dimension — the remaining work below is the rest of general-purpose
observability, not the tier-specific slice.

**Architecture decision (propose, confirm before building):** structured logging via stdlib
`logging` + a JSON formatter, extended repo-wide (not just quota events) in
`apps/api`/`apps/worker`; error tracking via `sentry-sdk`'s FastAPI integration (needs a
`SENTRY_DSN` — external account, human decision, not mine to provision); request-latency
metrics via `prometheus-fastapi-instrumentator` added to the existing `/metrics` endpoint
(don't create a second endpoint — extend the one Phase 1 already built), scraped by a real
`infra/monitoring/prometheus/prometheus.yml` (replacing the placeholder), with one minimal
Grafana dashboard (request rate, error rate, p95 latency, `/query` volume, and a
tier-breakdown panel now that the data exists) checked into
`infra/monitoring/grafana/dashboards/`.

**This phase needs its own detailed plan before implementation** (Sentry DSN provisioning is a
human decision; dashboard panel choices benefit from a short design pass) — write it with
superpowers:writing-plans when this phase starts. Task-level breakdown for now:

- [ ] **3.1** Structured JSON logging in `apps/api` + `apps/worker`, repo-wide (request id, user
      id where available, latency per request via middleware) — S/M
- [ ] **3.2** `sentry-sdk` integration behind `SENTRY_DSN` env var (no-op if unset, so local dev
      isn't forced to have an account) — S
- [x] ~~**3.3** `/metrics` endpoint~~ — done in Phase 1; extend it with
      `prometheus-fastapi-instrumentator` for request-latency histograms — S
- [ ] **3.4** Real `infra/monitoring/prometheus/prometheus.yml` scrape config targeting the
      `api`/`worker` k8s services — S
- [ ] **3.5** One Grafana dashboard JSON (request rate / error rate / p95 latency / query
      volume / tier breakdown) checked into the repo — M
- [ ] **3.6** Wire Prometheus scrape annotations onto `infra/kubernetes/base/api/deployment.yaml`
      (and worker, if it gains metrics too) — S

### Checkpoint: Phase 3
- [ ] A deliberately-triggered error in staging shows up in Sentry within seconds
- [ ] `/metrics` returns real Prometheus-format output locally
- [ ] Grafana dashboard renders non-zero data against local Prometheus scraping local `/metrics`

**Open question:** Sentry (or another provider) requires an external account and a DSN secret —
that provisioning step is a human/business decision (cost, data-residency for legal-adjacent
data), not something to default silently.

---

## Phase 4 — Legal/compliance content 🔴

**Why:** No ToS/privacy page exists anywhere in `apps/web`, and this product stores user
questions (which may describe someone's personal legal/housing situation) plus email/password.
The disclaimer is already solid (structurally guaranteed on every `QueryResponse`) — this
phase is the two things around it that are missing.

**Important constraint:** I should not author binding legal text (ToS/privacy policy language)
as if it were reviewed legal copy — that's a genuine liability risk for a legal-adjacent
product. My role here is the *engineering* half: build the page/route, the data-retention
factual summary (what's actually stored, verifiable from the schema), and a placeholder legal
text block clearly marked "pending attorney review" — not to draft final legal language myself.

- [ ] **4.1** `apps/web` route + component for ToS/Privacy (`/legal` or footer-linked static
      page), linked from `AuthScreen`/`LoginForm`/`RegisterForm` and app footer — S
- [ ] **4.2** Factual data-retention summary (what's stored: email, bcrypt hash, conversation
      questions/answers/citations; what's not: no payment data, no third-party tracking beyond
      Anthropic API calls for generation) — derived directly from `migrations/postgres/*.sql`,
      not guessed — S
- [ ] **4.3** Placeholder legal text clearly marked pending attorney review, so this doesn't
      silently ship as final — XS

### Checkpoint: Phase 4
- [ ] `/legal` route renders and is reachable from both auth screens
- [ ] Data-retention summary cross-checked line-by-line against actual migrations (no claims
      not backed by schema)
- [ ] Explicit flag in the PR description: legal text needs attorney sign-off before this is
      truly "done" for GA — this checkpoint is engineering-complete, not legally-complete

---

## Phase 5 — Legal corpus expansion 🔴

**Why:** 18 statute sections + 3 cases is a toy dataset. Real NY landlord-tenant law spans
dozens of RPAPL/RPL/GOL sections and much more controlling case law — the system currently
abstains or mis-answers most real questions outside its narrow seed set.

**Delegate to the `data-ingestion` agent** — this repo already has one scoped exactly to
`pipelines/ingestion/{ny_legislation,ny_case_law}`. Don't reinvent the ingestion process here.

- [ ] **5.1** Audit current statute coverage against a real NY landlord-tenant practice
      checklist (e.g. eviction proceedings, warranty of habitability, security deposits, rent
      stabilization basics) — identify concrete missing RPAPL/RPL/GOL sections — M
- [ ] **5.2** Expand `pipelines/ingestion/ny_legislation/seed_statutes.json` with the identified
      sections (via the existing NY Open Legislation API client — see the
      `ny-open-legislation-api` skill) — M/L, can parallelize by statute chapter
- [ ] **5.3** Source additional case law within the constraint ADR-0006 already established
      (no viable free automated full-text source — must be hand-curated via an authenticated
      CourtListener token, same process as the existing 3 seed cases) — L, bounded by how many
      cases are curated per pass
- [ ] **5.4** Expand `tests/evaluation/golden_questions.yaml` to cover the new corpus and run
      `scripts/evaluate.sh` to confirm no regressions on existing questions — M

### Checkpoint: Phase 5
- [ ] Golden-question pass rate holds or improves after ingesting the expanded corpus
      (regressions here mean chunking/retrieval tuning is needed, not just more data)
- [ ] Manual spot-check: 5 realistic landlord-tenant questions outside the original 3-case set
      now retrieve relevant, cited passages instead of abstaining

**Open question:** how much corpus is "enough" for GA is a product decision, not purely
technical — worth explicitly deciding a minimum coverage bar (e.g. "all RPAPL Article 7 +
top N Appellate Division landlord-tenant cases") rather than expanding indefinitely.

---

## Phase 6 — CI/CD & infra hardening (final pass before GA) 🟡

**Why:** Infra/CI foundations are real (not vaporware) but self-documented as demo-grade:
local Terraform state, no deploy workflow, integration/e2e tests are manual-only, single-node
Postgres with no backup/DR.

- [ ] **6.1** Gate `tests/integration/` in CI — spin up a `db-test` Postgres+pgvector service
      container in a new/extended workflow, run the real-DB suite on every relevant PR, not
      manually only — M
- [ ] **6.2** Replace the `tests/end_to_end` stub with at least one real smoke test (login →
      query → see a cited, disclaimered answer) — M
- [ ] **6.3** Add an actual deploy workflow (build+push image to ECR, trigger ArgoCD
      sync/kubectl apply) — or, if full CD automation is out of scope for this GA, write an
      explicit manual deploy runbook so "how do we ship a fix" isn't tribal knowledge — M
- [ ] **6.4** Move Terraform state to a remote backend (S3 + DynamoDB lock table) instead of
      local state — S
- [ ] **6.5** Define a Postgres backup/DR strategy for the k8s StatefulSet (scheduled
      `pg_dump` to S3 at minimum, or migrate to a managed RDS instance) — M

### Checkpoint: Phase 6
- [ ] A PR touching `tests/integration` shows those tests running in the Actions log, not just
      locally
- [ ] `terraform plan` against the remote backend shows no unexpected drift after migration
- [ ] A documented (and ideally rehearsed) restore-from-backup procedure exists for Postgres

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Tier quotas (15/50/100 per 4h) set from guesses, not real traffic, block legitimate users | Medium | Limits are centralized constants in `quota.py` (`TIER_LIMITS`/`QUOTA_PERIOD`), easy to tune after real usage data |
| `/auth/login` still has no brute-force rate limiting (Phase 1's original scope, not carried into the tier-quota rework) | Medium | Small standalone follow-up: `slowapi`, `5/minute` per IP, `/auth/login` only |
| Sentry/observability vendor choice is a cost/compliance decision, not mine to make silently | Medium | Flag as an explicit open question in Phase 3, get human sign-off before provisioning |
| Legal text (ToS/privacy) shipped without attorney review reads as "done" | High | Phase 4 explicitly marks legal copy as placeholder pending review, not silently final |
| Corpus expansion (Phase 5) never converges — "more data" has no natural stopping point | Medium | Phase 5's open question forces an explicit minimum-coverage decision, not indefinite expansion |
| Conversation-ownership migration (Phase 2) run against a DB with real existing conversations | Low (currently no real users) | Migration adds nullable `user_id`; if this runs after real users exist, add a data backfill step first — not needed today |

## Suggested Execution Order

Phase 1 (tier quotas) is done. Phase 2 (conversation authz) is next — small, independent,
closes a real security gap. Phase 3 (observability) should land before Phase 5 (corpus
expansion) starts generating real production traffic to watch, and only needs to add the
general-purpose pieces Phase 1 didn't already cover. Phase 4 (legal content) is independent and
can run in parallel with anything. Phase 6 is explicitly last — it's the "harden what already
works" pass, not something blocking earlier phases.

```
Phase 0 (prep) ──┬── Phase 1 (tier quotas) ✅ done   ──┐
                  └── Phase 2 (conversation authz) ──────┼── Phase 3 (observability) ── Phase 5 (corpus) ── Phase 6 (CI/infra hardening)
                                                          │
                      Phase 4 (legal content) ────────────┘  (fully independent, run anytime)
```

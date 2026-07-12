# GA Go-Live Checklist

Flat tracking sheet — check items off as PRs merge. Full reasoning, acceptance criteria, and
file-level detail for each item live in
`docs/superpowers/plans/2026-07-12-ga-readiness-roadmap.md`; this file is just the scoreboard.

**Progress: 9 / 32 items complete (28%)** — update this line by hand as boxes get checked.

## Phase 0 — Prep
- [ ] 0.1 Fix `pipelines.yml` to actually run `apps/worker/tests`
- [ ] 0.2 `CORS_ALLOW_ORIGINS` set explicitly per deployment (not left on localhost default)

## Phase 1 — SaaS tier quotas 🔴 blocker — ✅ done 2026-07-12
- [x] 1.1 `users.tier`/`request_count`/`period_started_at` migration + ORM fields
- [x] 1.2 `quota.py`: atomic check-and-consume, race-safe (proven against real Postgres)
- [x] 1.3 `POST /query` returns 429 with `{tier, limit, reset_at}` once exhausted; `usage` attached to every success response
- [x] 1.4 Three demo users seeded (Bob/Silver, Steve/Gold, Jennifer/Platinum) via `.env` + `scripts/seed-demo-users.sh`
- [x] 1.5 `POST /auth/register` disabled (403) — only seeded users can log in
- [x] 1.6 Tier-labeled Prometheus counters + structured logs (pulls forward part of Phase 3)
- [x] 1.7 `TierBadge` in web UI shows live tier + usage + reset time
- [ ] 1.8 Follow-up (not done in this pass): `/auth/login` brute-force rate limiting (`slowapi`, 5/min/IP)

## Phase 2 — Conversation authorization 🔴 blocker
- [ ] 2.1 Migration: `conversations.user_id` added (renumbered `0005_...` — `0004` is now tiers)
- [ ] 2.2 `Conversation` ORM model updated
- [ ] 2.3 `handle_query_turn` scopes loads by `user_id`; cross-user access returns 404
- [ ] 2.4 Integration test (`tests/integration/test_conversations.py`) covers cross-user denial

## Phase 3 — Production observability 🔴 blocker (partially done via Phase 1)
- [ ] 3.1 Structured JSON logging in `apps/api` + `apps/worker`, repo-wide (Phase 1 only covers quota events)
- [ ] 3.2 Error tracking (Sentry or equivalent) wired behind `SENTRY_DSN`
- [x] 3.3 `/metrics` endpoint exposed (done in Phase 1 — still needs request-latency histograms via `prometheus-fastapi-instrumentator`)
- [ ] 3.4 Real Prometheus scrape config (replaces placeholder README)
- [ ] 3.5 One working Grafana dashboard checked into the repo (include a tier-breakdown panel)
- [ ] 3.6 Prometheus scrape wired onto k8s deployments

## Phase 4 — Legal/compliance content 🔴 blocker
- [ ] 4.1 ToS/Privacy route + page live in `apps/web`, linked from auth screens
- [ ] 4.2 Data-retention summary written, verified against actual schema
- [ ] 4.3 Legal text explicitly flagged pending attorney review

## Phase 5 — Legal corpus expansion 🔴 blocker
- [ ] 5.1 Statute coverage gap audit complete
- [ ] 5.2 `seed_statutes.json` expanded to cover identified gaps
- [ ] 5.3 Additional case law curated and seeded
- [ ] 5.4 `golden_questions.yaml` expanded; eval shows no regressions

## Phase 6 — CI/CD & infra hardening 🟡 partial
- [ ] 6.1 `tests/integration` gated in CI (not manual-only)
- [ ] 6.2 Real e2e smoke test replaces the empty stub
- [ ] 6.3 Deploy workflow automated, or manual runbook documented
- [ ] 6.4 Terraform remote state (S3 + DynamoDB)
- [ ] 6.5 Postgres backup/DR strategy defined and documented

## Sign-off gates (not code — human decisions required before flipping to GA)
- [ ] Legal counsel has reviewed and approved ToS/privacy text (Phase 4)
- [ ] Minimum legal-corpus coverage bar explicitly agreed (Phase 5's open question)
- [ ] Observability vendor (Sentry/etc.) selected and provisioned (Phase 3's open question)

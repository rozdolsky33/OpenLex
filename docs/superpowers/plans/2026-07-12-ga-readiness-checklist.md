# GA Go-Live Checklist

Flat tracking sheet — check items off as PRs merge. Full reasoning, acceptance criteria, and
file-level detail for each item live in
`docs/superpowers/plans/2026-07-12-ga-readiness-roadmap.md`; this file is just the scoreboard.

**Progress: 17 / 36 items complete (47%)** — update this line by hand as boxes get checked.

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

## Phase 2 — Conversation authorization 🔴 blocker — ✅ done 2026-07-12
- [x] 2.1 Migration: `conversations.user_id` added (renumbered `0005_...` — `0004` is now tiers)
- [x] 2.2 `Conversation` ORM model updated
- [x] 2.3 `handle_query_turn` scopes loads by `user_id`; cross-user access returns 404
- [x] 2.4 Integration test (`tests/integration/test_conversations.py`) covers cross-user denial

## Phase 3 — Production observability 🔴 blocker (superseded by expanded design)
See `docs/superpowers/specs/2026-07-12-production-observability-design.md` (approved) and
its per-phase implementation plans under `docs/superpowers/plans/2026-07-12-observability-phase*.md`
and `docs/superpowers/plans/2026-07-13-observability-phase2-tracing-and-ha.md`.
- [x] 3.3 `/metrics` endpoint exposed (done in the original Phase 1 tier-quota work)
- [ ] 3.2 Error tracking (Sentry or equivalent) — still explicitly out of scope; separate
      cost/compliance decision, not part of the observability design
- [x] 3.7 Observability Phase 1: kube-prometheus-stack + OTel Collector infra plumbing on kind
- [x] 3.7a Multi-node kind topology (1 control-plane + 3 workers): dedicated infra worker
      node (ArgoCD + entire observability stack) vs. 2 apps worker nodes, with a real
      `kubectl drain` proving the PDB survives a node disruption with zero downtime. Note:
      the anti-affinity is soft (`preferred`, not `required` — a hard rule would leave the
      evicted replica Pending on a 2-apps-node cluster) — disruption *survivability* is
      proven, but steady-state pod *spread* is best-effort and doesn't self-heal after a
      disruption (confirmed live: both replicas can end up on the same node post-drain)
- [x] 3.7b Tracing backends deployed and dual-verified: Tempo (primary) + Jaeger (comparison),
      OTel Collector exports the same trace to both, Grafana datasources for both pass their
      health check
- [x] 3.7c Loki + Promtail log aggregation deployed (ships every pod's stdout, including
      `apps/api`'s existing structured quota-event logs), Grafana Loki datasource healthy
- [x] 3.7d Two initial Grafana dashboards (Golden Signals — API saturation panels + explicit
      placeholders for the still-missing latency/traffic/error panels; Tier & Quota) —
      verified against real traffic, not synthetic data
- [ ] 3.8 Observability Phase 2 (app-level): `apps/api` emitting its own traces/spans via OTel
      SDK, and the request-duration histogram the Golden Signals dashboard is still waiting on
      — the infra-level Tempo/Jaeger backends exist (3.7b) but no application code sends
      traces to them yet
- [ ] 3.9 Observability Phase 3: `apps/worker` OTel instrumentation + `postgres_exporter`
- [ ] 3.10 Observability Phase 4: `apps/web` browser tracing
- [ ] 3.11 Alertmanager symptom-based alert rules (error rate, p99 latency, quota burn) — Loki
      itself is done (3.7c), this item is specifically the alerting rules, still open

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

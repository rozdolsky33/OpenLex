# GA Go-Live Checklist

Flat tracking sheet — check items off as PRs merge. Full reasoning, acceptance criteria, and
file-level detail for each item live in
`docs/superpowers/plans/2026-07-12-ga-readiness-roadmap.md`; this file is just the scoreboard.

**Progress: 20 / 37 items complete (54%)** — update this line by hand as boxes get checked.

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
- [x] 3.8 Observability Phase 2 (app-level): `apps/api` emits real traces via OTel SDK
      (FastAPI/SQLAlchemy/httpx auto-instrumentation), manual `user.tier`/`user.id`/
      `conversation.id` span attributes on `/query`, and quota-event logs correlated with
      `trace_id` — all live-verified end-to-end (a real `/query` call's trace in Jaeger carries
      the right attributes with zero PII; the matching Loki log line carries the same
      `trace_id`). The Golden Signals dashboard's traffic/error/latency panels are still
      explicitly placeholders — no OTel *metrics* pipeline exists yet, only tracing (see 3.9's
      note); this is the one remaining Golden Signals gap, tracked separately, not silently
      dropped.
- [x] 3.9 Observability Phase 3: `apps/worker` OTel instrumentation (with explicit
      `force_flush()` before exit, verified live — a 16ms-lifetime ingest process still
      produced a complete trace) + `postgres_exporter`/`pg_stat_statements` deployed and
      live-verified post-merge end-to-end (Postgres → exporter → Prometheus → Grafana all
      show real non-zero data, not just that the exporter process runs). One real secret leak
      was caught and fixed during this work: the NY Open Legislation API key was appearing in
      cleartext in httpx span attributes; now redacted.
- [ ] 3.10 Observability Phase 4: `apps/web` browser tracing
- [ ] 3.11 Alertmanager symptom-based alert rules (error rate, p99 latency, quota burn) — Loki
      itself is done (3.7c), this item is specifically the alerting rules, still open
- [x] 3.12 Observability revisit (2026-07-13): closed the Golden Signals metrics gap flagged in
      3.8/3.9's notes — `apps/api/src/openlex_api/http_metrics.py` adds a hand-rolled
      `prometheus_client` RED middleware (`openlex_http_requests_total` +
      `openlex_http_request_duration_seconds`, route-templated labels, `/metrics` itself
      excluded from its own counters) rather than wiring a second OTel metrics pipeline just
      for this. Golden Signals dashboard's traffic/error-rate/p50-p95-p99 panels replaced with
      real queries against it, live-verified. Also fixed in this pass, all live-verified
      against the running kind cluster (not just code review):
      - ArgoCD `application-controller` was OOMKilling every ~5min on a stale 256Mi limit —
        768Mi was already committed (788ce4c) but `helm upgrade` had never been re-run to
        apply it.
      - otel-collector's Prometheus self-metrics port (8888) was never enabled
        (`ports.metrics.enabled` defaults to `false` in the chart) — the ServiceMonitor
        existed but had zero scrape targets, so no `otelcol_*` series existed anywhere. Fixed,
        plus a new OTel Collector Grafana dashboard (receiver accept/refuse, exporter
        sent/failed/queue-saturation, process health) now exists in the Observability folder.
      - Tier & Quota dashboard's two stat panels were rendering as a wall of repeated
        tier-name text — `reduceOptions.values: true` on a non-instant range query renders one
        box per returned row (timestamp), not one per series. Fixed (`values: false` +
        `instant: true` on the targets).
      - Golden Signals' memory panel had a missing `sum by (pod)` aggregation, unlike its
        sibling CPU panel — cAdvisor emits per-container and pod-level rows, producing
        duplicate legend entries per pod.
      - `apps/web` is now wired into the kind overlay (previously excluded — the exclusion
        comment predated apps/web having a Dockerfile) and reachable locally via the new
        `scripts/app-port-forward.sh`; `scripts/observability-port-forward.sh` now also
        forwards `argocd-server`.
- [x] 3.13 SRE dashboard strategy (2026-07-13, PR #18, merged) — see
      `docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md` and its
      implementation plan `docs/superpowers/plans/2026-07-13-sre-dashboard-strategy.md`. Adds
      audience-tiered Grafana dashboards on top of the existing stack (Applications/Engineering
      already had Golden Signals + Tier & Quota; this pass adds a User Journey / Trace Explorer
      dashboard there, plus new Product, Executive, and On-Call folders/dashboards) and
      Anthropic API cost/token/latency/error observability (`legal_generation.anthropic_metrics`,
      wired into `generate_answer` with rate-limit/api-error/connection-error classification,
      zero `/query` behavior change). Two concrete bugs found and fixed along the way:
      `scripts/observability-port-forward.sh` never actually forwarded Jaeger (likely root cause
      of prior difficulty cross-referencing traces there), and `/healthz` was excluded from
      neither tracing nor RED metrics despite being hit continuously by k8s probes. Also adds
      `X-Trace-Id` response headers and stable Tempo/Jaeger/Loki Grafana datasource UIDs (they
      previously had none, an unpredictable-UID bug the design review caught). All four new/
      touched dashboards were live-verified against the real `kind-openlex` cluster
      (ConfigMaps applied, files confirmed mounted in the Grafana pod, panel PromQL/TraceQL
      spot-checked against live Prometheus/Tempo); a final whole-branch review caught one real
      bug pre-merge (a PromQL vector-matching mismatch that would have left the Product
      dashboard's abstain-rate panel silently empty) plus three minor issues, all fixed and
      re-verified. **3.10 (browser tracing) and 3.11 (Alertmanager symptom-based rules) remain
      open** — explicitly out of scope for this pass, tracked as-is, not touched or narrowed by
      it. The On-Call dashboard's `dashboard_url` alert-annotation wiring is a small follow-on
      once 3.11 lands, not a blocker for the dashboard's existence.
- [x] 3.14 Post-3.13 hardening (2026-07-14, PRs #19–#22, all merged) — four follow-up fixes
      found via live use of the 3.13 dashboards, not part of that pass's original scope:
      - **#19** Tempo's Grafana datasource had empty `jsonData` — the Service Graph panel had
        no Prometheus datasource to query for `traces_service_graph_*` metrics (which
        genuinely existed, 46 real series) and always rendered empty. Fixed:
        `jsonData.serviceMap.datasourceUid: prometheus`.
      - **#20** Three real dashboard bugs plus a build-tooling bug, all live-verified:
        On-Call's error-rate panel had no zero-guard (`OR on() vector(0)`), so zero 5xx errors
        showed "No data" instead of "0%"; `infrastructure/nodes-aix.json`/`nodes-darwin.json`
        removed (stock kube-prometheus-stack dashboards for OSes this Linux-only kind cluster
        never runs, permanently empty by design); the repo had no `.dockerignore`, so every
        `apps/api`/`apps/worker` build copied six stale `.claude/worktrees/*` checkouts
        (~5GB, each with its own venv) into the build context — this was also the proximate
        cause of `openlex-api` running 16+-hour-stale code (a `docker build` failure from a
        full Docker Desktop VM disk), fixed alongside redeploying it with 3.13's actual code.
      - **#21** Tempo ran on the chart's default emptyDir, not a PVC — confirmed live it lost
        all trace data on every pod restart and, once the shared node disk filled, started
        failing writes entirely (`"failed to cut traces... no space left on device"`; a real
        trace's direct ID lookup 404'd despite the Collector reporting successful export).
        Gave it a dedicated 10Gi PVC (same convention `loki`'s `singleBinary.persistence`
        already uses); verified end-to-end post-fix with a real trace's direct ID lookup
        returning 200 with the full span waterfall.
      - **#22** `apps/api`'s OTel Resource now carries `k8s.pod.name`/`k8s.node.name` (via
        Downward API + `OTEL_RESOURCE_ATTRIBUTES`, zero application code change — Jaeger
        "Process" tags / Tempo `resource.*`, not per-span attributes, since pod/node identity
        is fixed for a container's lifetime). Verified live: a real trace's resource
        attributes show the exact pod/node that served the request.
      **3.10 and 3.11 remain open and untouched by any of this** — none of #19–#22 add browser
      tracing or alerting rules; they're fixes to what 3.13 already shipped.

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

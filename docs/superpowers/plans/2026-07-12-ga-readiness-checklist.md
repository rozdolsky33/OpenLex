# GA Go-Live Checklist

Flat tracking sheet — check items off as PRs merge. Full reasoning, acceptance criteria, and
file-level detail for each item live in
`docs/superpowers/plans/2026-07-12-ga-readiness-roadmap.md`; this file is just the scoreboard.

**Progress: 37 / 52 items complete (71%)** — update this line by hand as boxes get checked.
(Recount 2026-07-14: Phase 7 grew again with 7.7-7.9 — node topology, static CDN hosting,
observability ingress/auth — added during design review after further requirements came in.
Progress % naturally dips as scope is discovered, not regresses; 37 done items is unchanged.)

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

## Phase 3 — Production observability 🔴 blocker (superseded by expanded design) — ✅ done
2026-07-14 modulo 3.2 (deliberately deferred, see below — not a silent gap)
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
- [x] 3.10 Observability Phase 4: `apps/web` browser tracing (2026-07-14, PR #24, merged) —
      Web SDK (`WebTracerProvider` + `BatchSpanProcessor` + OTLP/HTTP exporter,
      `StackContextManager`) wired in `apps/web/src/telemetry.ts`, root span per page load
      (`DocumentLoadInstrumentation`) + child span per `fetch()` call
      (`FetchInstrumentation`, `traceparent` propagated only to `VITE_API_BASE_URL`), gated
      on `VITE_OTLP_ENDPOINT` (unset = tracing silently skipped, matches the project's
      no-hardcoded-endpoint precedent). Collector's `otlp.protocols.http.cors` allowlist
      added for the dev-server origin. Live-verified end-to-end post-merge: real OTLP/HTTP
      exports succeed (200, with a preceding successful CORS preflight) from the browser;
      pulled a real trace (`542e10969289408618a70929f6edb03`) from Tempo rooted at
      `openlex-web: HTTP POST` correctly chaining into the full `apps/api` server-side
      waterfall (DB spans, `anthropic.messages.create`), proving genuine cross-service trace
      propagation, not just isolated browser spans. **Finding, not fixed in this pass:**
      `X-Trace-Id` response header isn't exposed via CORS (`Access-Control-Expose-Headers`
      missing from `apps/api`'s CORS middleware config), so browser JS reading it via
      `fetch()` gets `null` — a real but minor gap, doesn't block anything since Tempo/Jaeger
      lookup by trace ID still works without it.
- [x] 3.11 Alertmanager symptom-based alert rules (2026-07-14, PR #23, merged) — Loki itself
      was already done (3.7c); this item is specifically the alerting rules. 5 symptom-based
      rules added via `kube-prometheus-stack`'s `additionalPrometheusRulesMap` (carries the
      chart's release label automatically, required for `ruleSelectorNilUsesHelmValues: true`
      to pick it up): `HighErrorRate` (>5%/5m, `for: 2m`, page), `ElevatedErrorRate`
      (>1%/15m, `for: 15m`, ticket), `QueryLatencyP99High` (p99>6s, `for: 10m`, ticket),
      `QuotaBurnRate` (>5 quota-exceeded events/15m per tier, ticket),
      `PostgresConnectionSaturation` (>80% of `max_connections`, `for: 5m`, ticket). Chart's
      default Alertmanager route still sends everything to a `"null"` receiver by design — no
      paging integration exists yet; this item was scoped to the rules themselves, not
      notification delivery.
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
      once 3.11 lands, not a blocker for the dashboard's existence. (Both closed 2026-07-14 —
      see 3.10/3.11 above.)
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
      tracing or alerting rules; they're fixes to what 3.13 already shipped. (Both closed
      2026-07-14 — see 3.10/3.11 above.)

## Phase 4 — Legal/compliance content 🔴 blocker — engineering-complete 2026-07-14, attorney
sign-off still required (see Sign-off gates below — that part is a human decision, not code)
- [x] 4.1 ToS/Privacy route + page live in `apps/web` (`/legal`, no router dependency added —
      checked via `window.location.pathname` in `App.tsx` since it's the only second route),
      linked from `AuthScreen` (reachable pre-login, since it's checked before
      `AuthProvider`/`AuthGate` mount) and from `ChatPage`'s header (reachable post-login).
      Live-verified in-browser: both links navigate correctly, the page's own "Back to
      OpenLex" link returns to the app.
- [x] 4.2 Data-retention summary written and verified line-by-line against
      `migrations/postgres/*.sql` (0001-0005): what's stored (email + bcrypt password hash,
      tier + rolling request counter, per-turn question/answer/citations/abstained flag) and
      what isn't (no payment data — the product has no billing; no analytics/ad trackers).
      Also states, verified against `packages/legal_generation/generator.py`, that
      questions/passages/history are sent to the Anthropic API for generation but
      email/password never are, and that there's currently no automated retention/deletion
      policy (`ON DELETE CASCADE` on `conversations.user_id` is the only cleanup mechanism,
      and only fires on manual user deletion).
- [x] 4.3 Legal text explicitly flagged pending attorney review — ToS and Privacy Policy each
      in their own visually-distinct (amber) section headed "draft, pending attorney review"
      with placeholder-intent text only, kept separate from the factual data-retention section
      above (which is engineering-verified, not legal copy, and isn't flagged as pending).

## Phase 5 — Legal corpus expansion 🔴 blocker — done 2026-07-14, scoped per CLAUDE.md's
"credible, not complete" philosophy (this is an SRE/Platform interview POC, not a real GA
legal product — see CLAUDE.md's "Why this project exists" section)
- [x] 5.1 Statute coverage gap audit complete — ran live against the real NY Open Legislation
      API document trees for RPAPL/RPL/GOL (not guessed citations). Found RPL Article 6-A
      "Good Cause Eviction Law" (NY's 2024 reform) 100% missing, plus real gaps in RPAPL
      Article 7 (eviction procedure), Article 7-A (repair-enforcement/HP proceedings, 0/15
      seeded), RPL Article 7 "Landlord and Tenant", and GOL Article 7 (security deposits).
- [x] 5.2 `seed_statutes.json` expanded 18 -> 64 sections. All 44 new candidate locationIds
      verified against the live API before adding (no guessed citations). Ingested against the
      running kind-openlex cluster: 64 documents / 64 chunks, 0 errors. Hit a real disk-
      exhaustion incident mid-ingest (Docker Desktop's shared VM disk, not Postgres' own PVC)
      — see `docs/postmortems/2026-07-14-disk-exhaustion-during-ingest.md` for the full
      root-cause writeup; no data loss, clean recovery, verified before retrying.
- [x] 5.3 Additional case law curated and seeded — kept intentionally small (2 more cases, 3
      -> 5 total) per the scope philosophy: enough to prove the seed-curation pipeline isn't
      hardcoded to 3, not a large manual-curation exercise. Both found and verified live via
      CourtListener's search API (not guessed), fetched via the authenticated detail endpoint
      per ADR-0006's process: Chinatown Apartments v. Chu Cho Lam (51 N.Y.2d 786) and ATM One,
      LLC v. Landaverde (2 N.Y.3d 472), both on notice-to-cure requirements tied to the RPAPL
      Article 7 sections just expanded in 5.2.
- [x] 5.4 `golden_questions.yaml` expanded (21 -> 28 questions) — **does not show "no
      regressions"; this is reported honestly, not glossed over.** Re-running the suite
      against the expanded corpus surfaced a real retrieval-recall regression (7/28 failing:
      5 hard-abstains, 2 imprecise citations) caused by corpus-scale dilution, most visibly
      RPAPL Article 7-A's near-duplicate procedural structure competing with Article 7 for
      generic queries. Root-caused via direct `hybrid_search`/RRF inspection against the real
      corpus. Found and fixed one real structural bug along the way (no per-document cap in
      `hybrid_search` let a single multi-chunk case occupy 4+ of 8 top-k slots) —
      `packages/legal_retrieval/src/legal_retrieval/search.py`, covered by a new regression
      test. That fix helped (all 7 new questions plus one existing one now pass) but didn't
      close the remaining 6 gaps; deeper retrieval-quality tuning was judged disproportionate
      ML-engineering effort for this project's actual scope (see CLAUDE.md) and was
      deliberately not pursued. Net: **22/28 passing (up from 21/28 pre-expansion)**, with the
      6 known gaps documented directly in `golden_questions.yaml`'s header rather than hidden
      by loosening assertions. `apps/api` rebuilt/redeployed with the fix and re-verified live
      against the running cluster.

## Phase 6 — CI/CD & infra hardening — ✅ done 2026-07-14 (PRs #27, #28, #29, #30 + a direct
docs commit, all merged to `develop` then promoted to `main` via #31)
- [x] 6.1 `tests/integration` gated in CI — real Postgres+pgvector service container
      (`integration.yml`), not manual-only anymore
- [x] 6.2 Real e2e smoke test replaces the empty stub — `tests/end_to_end/test_smoke.py`,
      gated on every PR (`smoke.yml`)
- [x] 6.3 Deploy workflow automated — `deploy.yml`: real multi-arch (amd64+arm64) build, push
      to GHCR, GitOps-commit back to `develop`, ArgoCD auto-syncs. Live-verified twice,
      including finding and fixing two real bugs (`root-kind.yaml`'s stale `targetRevision`;
      the QEMU/multi-arch crash) that only surfaced by watching the pipeline actually run.
- [x] Environment/branch model (added during design, not originally scoped): `develop` =
      staging (kind+ArgoCD), `main` = reserved for a real future production/EKS environment.
      See `docs/infrastructure/dev-workflow-and-branching.md`.
- [x] Docker-compose observability parity (added during design, not originally scoped):
      OTel Collector + Prometheus + Grafana + Jaeger added to the local dev loop.
- 6.4 (Terraform remote state) and 6.5 (Postgres backup/DR) **moved to Phase 7** below — see
      the roadmap doc's Phase 6 "Scope note" for why.

## Phase 7 — AWS-flavored production path: RDS, Secrets Manager, External Secrets 🔴 blocker
Design spec approved and committed (`docs/superpowers/specs/
2026-07-14-phase7-aws-rds-secrets-manager-design.md`) — implementation plan not yet written.
Design/build only this pass, no live AWS deployment (confirmed with the user).
- [ ] 7.1 Design + implement: RDS Postgres (pgvector) for production, replacing the in-cluster
      StatefulSet. Includes a corrected VPC assumption (public-subnets-only, no NAT Gateway —
      RDS joins existing public subnets with `publicly_accessible=false` + security groups as
      the real isolation boundary) and a documented `kubectl` debug-pod pattern for occasional
      operator access instead of a bastion/SSM setup.
- [ ] 7.2 Verify + complete (not rebuild): the existing but never-live-verified Secrets
      Manager + External Secrets Operator manifests for production/EKS
- [x] 7.3 Environment isolation — **resolved as "no new code needed."** Local kind never gains
      any path to real AWS resources, not even optional (a hybrid bootstrap mode was
      considered during design and deliberately dropped — see the spec's 7.3). Local stays
      100% local, cloud stays 100% cloud.
- [ ] 7.4 Terraform remote state (S3 + DynamoDB) — was 6.4
- [ ] 7.5 Postgres backup/DR strategy — was 6.5, resolved via 7.1's RDS automated backups
- [ ] 7.6 Cloud observability (added during design, not in the original sketch): AWS-native
      managed backends (X-Ray for traces, CloudWatch for metrics/logs via the same OTel
      Collector config already proven on kind/compose) instead of copying kind's full
      self-hosted stack — cheap, no dedicated observability node needed on eks-demo's
      currently-single-node cluster. One small self-hosted Grafana stays the shared viewing
      layer across kind and eks-demo (CloudWatch + X-Ray as Grafana datasources).
- [ ] 7.7 Node topology (added during design): split the single EKS node group into
      `observability` (t4g.large, mirrors kind's dedicated tainted node) + `apps` (t4g.medium,
      fixed 2 nodes/1 per AZ, real multi-AZ HA with **hard** anti-affinity — stronger than
      kind's soft-only version, since EKS can actually replace a drained node). Adds the
      `aws-ebs-csi-driver` addon (not present today) for Prometheus/Loki/Tempo's PVs.
- [ ] 7.8 Static content (added during design): `apps/web` gains a real production build
      (`vite build`, not the dev-server-in-a-container it's always been) served via S3 +
      CloudFront, with a new `deploy-static.yml` triggered on push to `main`. Splits
      `app.<domain>` (CloudFront/S3) from `api.<domain>` (ingress-nginx, unchanged).
- [ ] 7.9 Ingress + unified auth for the observability stack (added during design):
      `oauth2-proxy` in front of Grafana/Prometheus/Jaeger via ingress-nginx (one shared
      login for all three — neither has real built-in auth to unify otherwise). ArgoCD keeps
      its own separate, already-secure native login rather than double-gating it — stated
      explicitly as a scope decision, not "all four share one password."

## Sign-off gates (not code — human decisions required before flipping to GA)
- [ ] Legal counsel has reviewed and approved ToS/privacy text (Phase 4)
- [ ] Minimum legal-corpus coverage bar explicitly agreed (Phase 5's open question)
- [ ] Observability vendor (Sentry/etc.) selected and provisioned (Phase 3's open question)

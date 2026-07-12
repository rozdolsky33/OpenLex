# Production Observability — Design

**Status:** approved design, pending implementation plan
**Supersedes:** the task-level sketch in `docs/superpowers/plans/2026-07-12-ga-readiness-roadmap.md`
Phase 3 — this design is broader (adds distributed tracing, an OTel Collector, full
trace/log/metric correlation, and dashboards/alerting) than that roadmap's original bullet
list (`sentry-sdk`, `prometheus-fastapi-instrumentator`, one Grafana dashboard). Phase 3's
checklist in the roadmap should be considered replaced by this document once approved.

## Goal

Stand up a full observability stack on the local `kind` cluster (Prometheus, Grafana,
Alertmanager, Loki, Tempo, Jaeger, an OpenTelemetry Collector) with end-to-end context
propagation from the browser through `apps/api`/`apps/worker` to Postgres, so a single
`trace_id` correlates traces, logs, and metrics for any user journey, and the four golden
signals (latency, traffic, errors, saturation) are visible on dashboards per service plus
Postgres and cluster infra.

**Explicitly in scope:** dual trace backends (Tempo as the Grafana-native primary, Jaeger
running side-by-side for capability comparison — this is deliberate duplication, not an
oversight), full-stack instrumentation including the React frontend, Alertmanager with a
first cut of symptom-based alerts, and a defined dashboard set.

**Explicitly out of scope for this pass:** Sentry/external error-tracking SaaS (a separate
cost/compliance decision per the roadmap's own open question — not superseded by this doc),
distributed/production-shaped storage backends for Tempo/Loki (object storage, retention
tuning) — this is a laptop-scale kind deployment, and a real receiver for Alertmanager
(Slack/PagerDuty) — routes to a `null`/log receiver for now, swappable later without touching
rule definitions.

## Architecture

### Signal pipeline

Every process — the browser (`apps/web`), `apps/api`, `apps/worker` — uses the OpenTelemetry
SDK for all three signals (traces, metrics, logs) and pushes via OTLP to a single OTel
Collector running in-cluster. The Collector is the one place that fans out to multiple
backends, so backend choice is a Collector config change, not an app code change:

```
apps/web (browser)  ─┐
apps/api             ─┼─ OTLP/HTTP or gRPC ──▶  OTel Collector  ──▶ Tempo (primary)
apps/worker          ─┘                              │        └──▶ Jaeger (comparison)
                                                       ├──▶ Loki (OTLP native log ingestion)
                                                       └──▶ Prometheus (prometheus exporter + ServiceMonitor)
postgres_exporter ─── scraped directly by Prometheus (Prometheus-native exporter, no OTLP hop)
node-exporter / kube-state-metrics ─── bundled in kube-prometheus-stack, scraped directly
```

**Correlation key:** the W3C `trace_id` (from `traceparent`), not a separate `X-Request-ID`.
It is generated at the browser, propagated through every hop, and injected into every
structured log line via OTel's logging bridge, and surfaces as Prometheus exemplars on
latency histograms. This is what makes "click a slow request → see its trace → see its
logs" work without a second correlation scheme.

### Components (all deployed via ArgoCD Helm Applications)

| Component | Helm repo | Purpose |
|---|---|---|
| `kube-prometheus-stack` | `prometheus-community/helm-charts` | Prometheus, Grafana, Alertmanager, node-exporter, kube-state-metrics |
| `tempo` | `grafana/helm-charts` | Primary trace backend (single-binary, local storage) |
| `jaeger` | `jaegertracing/helm-charts` | Comparison trace backend (all-in-one, Badger/in-memory storage) |
| `loki` | `grafana/helm-charts` | Log aggregation (single-binary, local filesystem storage) |
| `opentelemetry-collector` | `open-telemetry/opentelemetry-helm-charts` | Central OTLP receiver + fan-out (deployment mode, not DaemonSet — apps push via SDK, no node log-tailing) |
| `prometheus-postgres-exporter` | `prometheus-community/helm-charts` | Postgres golden signals (connections, tx rate, cache hit ratio, slow queries) |

All of Tempo/Jaeger/Loki run in single-binary/all-in-one mode with local storage — this is a
comparison-and-learning setup on kind, not a production-shaped deployment.

## Per-app instrumentation

### `apps/web` (new instrumentation)

- OTel Web SDK (`sdk-trace-web` + `instrumentation-document-load` + `instrumentation-fetch`):
  root span per page load, child span per `fetch()` to `/auth/*` and `/query`, injects
  `traceparent`.
- Exports via OTLP/HTTP to the Collector.
- **New infra wiring required:** `apps/web` is currently scaffolded in
  `infra/kubernetes/base/web` but not referenced by `overlays/kind/kustomization.yaml` — it
  has never been deployed to kind. This design adds it to the kind overlay. The kind cluster
  has no ingress (port-forward only, existing convention) — the Collector's OTLP/HTTP port
  gets port-forwarded alongside the others, and `VITE_OTLP_ENDPOINT` points the browser SDK
  at the forwarded port.

### `apps/api` (FastAPI)

- Auto-instrumentation: `opentelemetry-instrumentation-fastapi` (server spans, continues the
  browser's trace), `-sqlalchemy` (DB query spans), `-httpx` (Anthropic API call spans — the
  `anthropic` SDK is httpx-based, so `traceparent` propagation there is automatic once httpx
  is instrumented).
- Manual span attributes, set as soon as known: `user.id`, `user.tier` (post
  `get_current_user`/quota check), `conversation.id` (once resolved in
  `handle_query_turn`). These become Tempo/Jaeger filters and Loki log fields.
- Logging: replace the ad-hoc `logging.info(json.dumps(...))` pattern in
  `apps/api/src/openlex_api/quota.py` with OTel's `LoggingHandler`, so every log record
  auto-carries `trace_id`/`span_id`/resource attributes and ships via OTLP to the Collector →
  Loki. Existing structured fields (`event`, `tier`, `request_count`, etc.) are unchanged,
  just riding the new handler.
- **PII guardrail:** never log the raw question/answer text at `info` level — a legal
  research query can describe someone's actual housing situation. Log length/hash, never
  content.

### `apps/worker` (ingestion CLI)

- One-shot process, not a long-running server — metrics/traces must be force-flushed before
  exit (`TracerProvider.shutdown()` / `MeterProvider.force_flush()`), or the last batch
  silently never ships. Verification step 5 below exists specifically to catch a regression
  here.
- Manual spans per pipeline stage (normalize → chunk → embed → upsert) per document, with
  `source`/`source_id`/`version` attributes. Its own trace per ingestion run — not chained to
  any user-journey trace, since ingestion isn't triggered by a live request.

### Database and infra metrics (no app code changes)

- `postgres_exporter` scrapes the existing Postgres directly. Requires enabling
  `pg_stat_statements` (`shared_preload_libraries=pg_stat_statements` in
  `infra/kubernetes/base/postgres/statefulset.yaml`, plus a restart) for slow-query
  visibility — not currently configured, and a real task in the implementation plan, not a
  silent assumption.
- node-exporter / kube-state-metrics (bundled in `kube-prometheus-stack`) cover node and
  pod-level saturation.

## Kubernetes / GitOps layout

- **Namespace:** new `observability` namespace for `kube-prometheus-stack`, `tempo`,
  `jaeger`, `loki`, `opentelemetry-collector`, and the dashboard ConfigMaps.
  `prometheus-postgres-exporter` deploys into the **`openlex`** namespace instead, so it can
  reference the existing `openlex-secrets` Secret directly via `envFrom` (no credential
  duplication across namespaces) — this works because Prometheus watches `ServiceMonitor`s
  across all namespaces by default.
- **ArgoCD Applications** under `infra/argocd/apps/kind/` (same shape as the existing
  `app-openlex.yaml`):
  - `app-kube-prometheus-stack.yaml` — sync-wave `-2` (its CRDs must exist before anything
    defines a `ServiceMonitor`)
  - `app-tempo.yaml`, `app-jaeger.yaml`, `app-loki.yaml`, `app-otel-collector.yaml`,
    `app-postgres-exporter.yaml` — sync-wave `-1`
  - `app-observability-dashboards.yaml` — kustomize path over
    `infra/monitoring/grafana/dashboards/` (`configMapGenerator`, `grafana_dashboard: "1"`
    label so the chart's sidecar auto-loads them — same pattern `base/postgres` already uses
    for init SQL)
- **`appproject-kind.yaml` changes:** add the four new Helm repo URLs to `sourceRepos` (same
  pattern `appproject-eks-demo.yaml` already uses for its own add-ons) and add
  `namespace: observability` to `destinations` (kept explicit, not switched to eks-demo's
  `"*"` wildcard, consistent with how scoped the kind project already is).
- **Resource footprint:** every chart gets explicit low `resources.requests` (same philosophy
  as the existing eks-demo cert-manager/ingress-nginx Applications). Total added footprint is
  roughly 1.5–2 vCPU / 2–3Gi memory requests on top of what `openlex` itself already uses —
  should be fine on a normal dev laptop, will size down further if `kubectl top pods` shows
  it's tight.
- **Access:** `scripts/observability-port-forward.sh` backgrounds `kubectl port-forward` for
  Grafana, Prometheus, Alertmanager, Jaeger, and the Collector's OTLP/HTTP port in one
  command, consistent with the existing "no ingress in kind, port-forward only" convention.

## Golden-signal SLOs and alerting

**SLO targets** (explicitly initial guesses, not derived from real traffic — same honesty as
the existing tier-quota risk note in the GA roadmap; revisit once there's real usage data):

- Availability: 99% error-free (non-5xx) over a 30-day window for `/query` and `/auth/*` —
  not 99.9%: single-replica API, single-node Postgres, no HA, so five-nines would be fiction.
- Latency: `/query` p95 < 3s / p99 < 6s (embedding + hybrid retrieval + an Anthropic call is
  inherently slower than CRUD); `/auth/*` p95 < 300ms.

**Alert rules** (Alertmanager, enabled this pass):

| Alert | Expression (sketch) | Severity |
|---|---|---|
| `HighErrorRate` | 5xx ratio on `/query`+`/auth.*` > 5% over 5m | page* |
| `ElevatedErrorRate` | > 1% over 15m | ticket |
| `QueryLatencyP99High` | p99 > 6s sustained 10m | ticket |
| `QuotaBurnRate` | `openlex_query_quota_exceeded_total` rate per tier sustained high over 15m | ticket |
| `PostgresConnectionSaturation` | active connections near `max_connections` | ticket |

*routed to a `null`/log receiver for now — visible in the Alertmanager UI, structured so a
real Slack/PagerDuty receiver can be swapped in later without touching rule definitions.
kube-prometheus-stack's bundled infra alerts (pod crash-looping, etc.) stay enabled at their
defaults — these five are additive.

## Dashboards

Checked into `infra/monitoring/grafana/dashboards/`, auto-provisioned via the
kube-prometheus-stack sidecar:

1. **Golden Signals — API** (traffic/errors/latency p50/p95/p99/saturation, per route)
2. **Golden Signals — Worker** (ingestion job rate/errors/duration/saturation)
3. **Tier & Quota** (`openlex_query_requests_total`/`_quota_exceeded_total`, by tier)
4. **Postgres** (connections, tx rate, cache hit ratio, slow queries — based on the standard
   community postgres-exporter dashboard, trimmed to what's relevant)
5. **Kubernetes Infra** (node CPU/mem/disk, pod restarts — mostly stock kube-prometheus-stack
   dashboards)
6. **User Journey / Trace Explorer** (Tempo service graph + a view pivoting on
   `user.tier`/`conversation.id` span attributes)
7. **Logs (Loki) Explore view** with derived-field links: log line → matching Tempo trace,
   and Tempo trace → matching Loki logs (bidirectional)

## Verification plan

Per the observability skill's "prove it, don't assert it" rule — these are executed, not just
claimed:

1. Generate synthetic `/query` traffic → confirm RED metrics populate with sane
   p50/p95/p99, and a histogram exemplar click-through reaches a real trace.
2. Force a 500 → confirm it appears on the Errors dashboard, `ElevatedErrorRate`/
   `HighErrorRate` fires in Alertmanager (temporarily lowering thresholds to trigger on
   demand), and the failing trace is visible in **both** Tempo and Jaeger with the same
   `trace_id`.
3. Follow one real browser → `/query` request end-to-end in the Tempo UI and separately in
   the Jaeger UI — no broken spans in either.
4. Click a log line in Loki → jumps to its Tempo trace, and a Tempo span → matching Loki
   logs. Both directions, not just one.
5. Run a small ingestion via `apps/worker` → confirm its trace shows up complete (proves
   force-flush-before-exit actually works).
6. Confirm `postgres_exporter` metrics (connections, cache hit ratio, slow queries) appear
   only after `pg_stat_statements` is enabled (proves that task actually landed against a
   configured Postgres, not an unconfigured one).

## Phased rollout

1. **Infra plumbing** — kube-prometheus-stack + OTel Collector deployed via ArgoCD into
   kind; existing `prometheus_client` `/metrics` scraped as-is (no app code changes yet).
   Proves GitOps/deployment mechanics before touching app code.
2. **Backend instrumentation** — `apps/api` (FastAPI/SQLAlchemy/httpx auto-instrument +
   manual `user.tier`/`conversation.id` attributes + OTel logging handler), wired to Tempo +
   Jaeger dual-export. Verify backend-only traces/logs correlate.
3. **Worker + database** — `apps/worker` ingestion spans (with force-flush),
   `postgres_exporter` + `pg_stat_statements` enablement.
4. **Browser tracing** — wire `apps/web` into the kind overlay, OTel Web SDK, Collector OTLP
   port exposed to the browser — completes the real end-to-end user journey.
5. **Logs + dashboards + alerts** — Loki OTLP ingestion, Grafana derived-field correlation,
   all 7 dashboards, Alertmanager rules, full verification pass.

Each phase leaves `main` deployable, per the roadmap's global constraint — no phase depends on
a later phase's code existing first.

## Risks and open questions

| Risk | Mitigation |
|---|---|
| SLO thresholds (99% availability, 3s/6s latency) are guesses with no real traffic behind them | Centralized in this doc and the eventual alert-rule files, easy to retune once real usage data exists |
| Alertmanager has no real receiver configured | Explicit `null`/log receiver for now; swapping in Slack/PagerDuty is a config change, not a redesign |
| Running 6 new Helm-deployed components on a laptop-scale kind cluster is a meaningful resource add | All in single-binary/all-in-one modes with low explicit resource requests; will re-tune from `kubectl top pods` if tight |
| Browser OTLP export requires new port-forward + env var plumbing that doesn't exist yet for `apps/web` | Scoped as its own explicit task (Phase 4), not glossed over as "just add a library" |
| `pg_stat_statements` requires a Postgres server restart (`shared_preload_libraries`) | Explicit task in Phase 3, not a silent assumption that the exporter alone is sufficient |

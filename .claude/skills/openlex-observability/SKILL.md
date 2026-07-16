---
name: openlex-observability
description: Use when adding or changing metrics, traces, dashboards, or alert rules in OpenLex — instrumenting a new endpoint or pipeline step, adding a Prometheus counter/histogram, building or editing a Grafana dashboard JSON, wiring PrometheusRule alerts, or when a metric/trace/dashboard isn't showing data and the cause isn't obviously the application code.
---

# OpenLex Observability

Phase 3 of the GA checklist (traces, metrics, dashboards, alerting) is essentially complete —
this is the most mature, convention-heavy part of the repo, and also the part CLAUDE.md says
matters most (see its "Why this project exists"). The conventions below are deliberate design
decisions, not accidents; breaking them silently reintroduces bugs this project already found
and fixed once.

## Rule 1: metrics are hand-rolled `prometheus_client`, not an OTel metrics pipeline — except in the worker

`apps/api/src/openlex_api/telemetry.py` only calls `trace.set_tracer_provider`, never
`opentelemetry.metrics.set_meter_provider`. This is deliberate: wiring a second OTel metrics
pipeline (`MeterProvider` + exporter) to duplicate what `prometheus_client` already gives you
directly, scraped via `/metrics`, would be pure overhead for a long-running server. So for
`apps/api` (and `packages/legal_generation`), new metrics are plain `prometheus_client.Counter`/
`Histogram`/`Gauge` — see `http_metrics.py`, `quota.py`, `anthropic_metrics.py` for the pattern.

**`apps/worker` is the opposite** — it uses a real OTel `MeterProvider` + `OTLPMetricExporter`
(`apps/worker/src/openlex_worker/telemetry.py`), because it's a one-shot CLI job with no
long-lived `/metrics` endpoint for Prometheus to scrape; push-based OTLP export force-flushed
before process exit is the only way its metrics survive. **Don't add a `prometheus_client`
counter to worker code expecting it to show up anywhere** — there's nothing scraping it. If
you're instrumenting worker code, use the `MeterProvider` returned by `setup_telemetry()`.

## Rule 2: naming, cardinality, and the health-check exclusion

- Prefix: `openlex_<domain>_<unit>[_total]` (`openlex_http_requests_total`,
  `openlex_query_quota_exceeded_total`, `openlex_anthropic_tokens_total`).
- Route/path labels must be the **matched route template**, not the raw path — a request
  matching no route falls back to a fixed `"unmatched"` value. Never label with a raw path or
  path parameter; that's unbounded cardinality Prometheus will make you regret.
- `/metrics` and `/healthz` are excluded from RED metrics *and* tracing (see
  `http_metrics.py`'s `_EXCLUDED_ROUTES` and `telemetry.py`'s `excluded_urls`) — Prometheus's
  own scrape and k8s's liveness/readiness probes would otherwise show up as constant synthetic
  traffic polluting the traffic/error-rate panels. Probe failures are still covered — by k8s's
  own pod-not-ready/crashloop alerting, not application metrics. Apply the same exclusion to
  any new health/scrape-only endpoint.

## Rule 3: traces are dual-exported to Tempo and Jaeger with the same trace_id

The Collector exports every span to both backends identically — there is no separate
correlation scheme; the same `trace_id` opens the same trace in either UI. Key span attributes
for correlation: `user.tier`, `user.id`, `conversation.id`, set in
`apps/api/src/openlex_api/routers/query.py`. The Trace Explorer dashboard's `$tier`/
`$conversation_id` template variables filter on exactly these — if you add a new traced
operation that should be tier- or conversation-filterable, set the same attribute names, don't
invent new ones.

## Rule 4: dashboards — vendored vs. custom, and how a new one gets picked up

`infra/monitoring/grafana/dashboards/{kubernetes,infrastructure,observability}/*.json` are
**vendored** kube-prometheus-stack/mixin dashboards — don't hand-edit them; if you need
different panels, that's a custom dashboard in `applications/`, `product/`, `executive/`, or
`oncall/` instead (the four audience-tiered folders — see
`docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md` for which audience each
one serves and why they're separate rather than one collapsed mega-dashboard).

A new dashboard JSON just needs to land in the right folder under
`infra/monitoring/grafana/dashboards/` — the same `configMapGenerator` + `grafana_dashboard:
"1"` sidecar label picks it up automatically (`foldersFromFilesStructure: true` derives the
Grafana folder from the directory). No ArgoCD Application change, no new sync wave.

## Rule 5: alerts live in `additionalPrometheusRulesMap`, not a standalone `PrometheusRule`

`infra/monitoring/kube-prometheus-stack/values-base.yaml`'s `additionalPrometheusRulesMap`
(not a `PrometheusRule` manifest applied via kustomize) is required specifically because
`ruleSelectorNilUsesHelmValues` defaults to true — Prometheus only watches `PrometheusRule`s
carrying the chart's own release label, and only the values-driven mechanism adds that label
automatically. A rule applied any other way silently never gets picked up (same failure class
as the `serviceMonitorSelectorNilUsesHelmValues: false` override a few lines below it in the
same file, needed because `openlex-api`'s `ServiceMonitor` lives in a different namespace with
no chart label).

Existing alerts (`openlex.rules` group): `HighErrorRate` (>5% 5xx on `/query`+`/auth.*`, 5m,
`severity: page`), `ElevatedErrorRate` (>1%, 15m, `severity: ticket`), `QueryLatencyP99High`
(`/query` p99 > 6s, 10m), `QuotaBurnRate` (>5 quota-exhaustion rejections per tier in 15m),
`PostgresConnectionSaturation` (>80% of `max_connections`, 5m). Thresholds are explicit initial
guesses, live-verified to parse against the real running Prometheus, not derived from
production traffic — revisit once real usage data exists, don't treat them as tuned.
`severity: page` vs `severity: ticket` currently both route to Alertmanager's default `null`
receiver (no Slack/PagerDuty wired yet) — the label split is intentional so a real receiver can
be plugged in later without touching rule definitions; don't remove it as "unused."

## Rule 6: Anthropic cost/token tracking is a static, manually-maintained pricing table

`packages/legal_generation/src/legal_generation/anthropic_metrics.py`'s
`ANTHROPIC_PRICING_PER_MILLION_TOKENS` does not self-update — it's hand-maintained against
Anthropic's published pricing, and an unrecognized model silently falls back to Sonnet-tier
default pricing rather than raising (so a cost estimate always exists, just imprecise for a
brand-new model). If you add support for a new model, add its pricing here or the cost panels
will silently under/over-report for it.

## Quick reference

| Symptom | Cause | Fix |
|---|---|---|
| New metric added, `/metrics` shows nothing (apps/api) | Wrong pipeline, or route not excluded correctly | Confirm it's a `prometheus_client` object registered at import time, not routed through OTel metrics (Rule 1) |
| New metric added in `apps/worker`, never shows up anywhere | Added a `prometheus_client` counter to a one-shot CLI with nothing scraping it | Use the `MeterProvider` from `setup_telemetry()` instead (Rule 1) |
| New Prometheus alert rule doesn't fire even though the expression is clearly true | Rule applied outside `additionalPrometheusRulesMap`, missing the chart's release label | Move it into `values-base.yaml`'s `additionalPrometheusRulesMap` (Rule 5) |
| New/moved app's metrics never appear in Prometheus at all | Its `ServiceMonitor` isn't in a namespace/labeled the way the chart's default selector expects | Check `serviceMonitorSelectorNilUsesHelmValues`/`ruleSelectorNilUsesHelmValues` in `values-base.yaml` (Rule 5) |
| New dashboard JSON added but doesn't appear in Grafana | Wrong folder, missing sidecar label, or edited a vendored dashboard expecting it to matter | Confirm the ConfigMap carries `grafana_dashboard: "1"` and lives under the right `dashboards/<folder>/` (Rule 4) |
| Traffic/error dashboards show constant low-level noise unrelated to real usage | A new endpoint wasn't added to the health-check/scrape exclusion list | Add it to `_EXCLUDED_ROUTES` (`http_metrics.py`) and `excluded_urls` (`telemetry.py`) (Rule 2) |

## Where the rest lives

- Stack design (Prometheus/Grafana/Tempo/Jaeger/Loki/OTel Collector topology, golden-signal
  SLOs): `docs/superpowers/specs/2026-07-12-production-observability-design.md`.
- Dashboard tier strategy (audience folders, Trace Explorer, cost/token panels):
  `docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md`.
- GA checklist Phase 3 items (3.7–3.14) for what's built and when: `docs/superpowers/plans/
  2026-07-12-ga-readiness-checklist.md`.
- kind vs. EKS cluster operation (context pinning, `gitops/*` delivery, ArgoCD selfHeal —
  relevant once you're deploying an observability change, not writing it): `eks-platform-ops`
  skill.
- Local bring-up/troubleshooting (stale port-forwards, empty-corpus/unseeded-user symptoms):
  `local-environment` skill.

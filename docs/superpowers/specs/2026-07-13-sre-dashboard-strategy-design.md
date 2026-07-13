# SRE Dashboard Strategy — Design

**Status:** approved design, pending implementation plan
**Builds on:** `docs/superpowers/specs/2026-07-12-production-observability-design.md` (the
stack this design's dashboards run on top of — Prometheus/Grafana/Tempo/Jaeger/Loki/OTel
Collector, already deployed via ArgoCD; GA checklist items 3.7–3.9, 3.12 done, 3.10 (browser
tracing) and 3.11 (alert rules) still open, unaffected by this doc).

## Goal

The observability *stack* is deployed and instrumented (Golden Signals — API, Tier & Quota
dashboards, dual Tempo/Jaeger tracing with `user.tier`/`user.id`/`conversation.id` span
attributes, trace-correlated logs). What's missing is a **dashboard strategy** — today
there's no differentiation between what an executive, a product owner, an on-call engineer,
and the owning engineering team each actually need to look at, no dedicated user-journey/trace
view, no visibility into Anthropic API cost/token usage, and two concrete gaps (health-check
noise polluting traffic/trace data, Jaeger never actually reachable via the port-forward
script) that this review surfaced.

**Explicitly in scope:** four audience-tiered Grafana dashboards (Executive / Product /
Engineering / On-Call) and their folder structure, a User Journey / Trace Explorer dashboard
(named in the original design doc but never built), Anthropic API cost/token/latency/error
instrumentation (currently zero visibility beyond an unlabeled httpx span), a response-header
fix for correlation-ID ergonomics, health-check trace/metric exclusion, and fixing the
port-forward script's missing Jaeger entry.

**Explicitly out of scope:** full browser-side tracing (`apps/web` OTel Web SDK — GA checklist
3.10, tracked as its own follow-up), Alertmanager symptom-based alert rules (3.11, tracked
separately — this design assumes those rules exist for the On-Call dashboard to link from, but
does not define them), tier-differentiated SLOs (silver/gold/platinum get one shared `/query`
SLO; tiers are a *filter*, not a different reliability target — no infra today actually treats
platinum preferentially, so a differentiated SLO would promise something the system doesn't
deliver), and session-stitching tooling that reconstructs a full multi-turn conversation as one
continuous trace timeline (Tempo/Jaeger don't support that natively; a table of per-turn traces
grouped by `conversation.id` is the pragmatic substitute — see below).

## Dashboard tier structure

Four Grafana folders, each with one dashboard scaled to how that audience actually works —
not a single mega-dashboard with collapsed rows (Grafana's row-collapse state doesn't reliably
persist across dashboard links, and an executive opening a collapsed engineering wall still
sees the wall).

| Folder | Dashboard | Audience | Cadence | Key panels |
|---|---|---|---|---|
| `Executive` | Executive Overview | Leadership | Monthly glance, refresh off | Query volume trend (30d), error-free % (vs. the 99% SLO), Anthropic cost trend, tier mix, active users, p95 latency (single line, no breakdown) |
| `Product` | Product & Usage | Product owner | Weekly, 7d default | Query volume by tier, abstain-rate trend, quota-exhaustion frequency by tier, doc-type mix (statute/case-law), conversation length distribution |
| `Engineering` | Golden Signals — API, Tier & Quota (existing), **User Journey / Trace Explorer** (new), Anthropic API row (new) | Owning team | 24h default, 30s refresh | Existing RED panels + trace waterfall + Anthropic latency/error/token breakdown |
| `On-Call` | Incident | Paged engineer | 15–60min default | Firing Alertmanager alerts (top row), golden signals clipped to the incident window, "top 5 slowest/failing traces right now" linking straight into the Trace Explorer pre-filtered to errors |

Dashboards link downward (Executive → Product → Engineering → On-Call) via Grafana's native
dashboard links. Alertmanager's alert annotations (`dashboard_url`, defined when 3.11 lands)
point directly at the On-Call dashboard — a paged engineer never has to go find it.

**Mechanics:** same provisioning already in use — new top-level folders
(`infra/monitoring/grafana/dashboards/{executive,product,oncall}/*.json`) alongside the
existing `applications/`, `observability/`, `infrastructure/`, `kubernetes/`, picked up by the
same `configMapGenerator` + `grafana_dashboard: "1"` sidecar pattern. No change to the ArgoCD
Application or sync-wave.

Two new Prometheus counters are needed for panels above that don't have a metric yet:
`openlex_query_abstained_total` (from `QueryResponse.abstained`, for Product's abstain-rate
panel) — everything else in this table reuses metrics that already exist.

## User Journey tracking & Trace Explorer

Full browser-to-response tracing needs `apps/web`'s OTel Web SDK (checklist 3.10, tracked
separately). Until then, a "journey" is the server-side waterfall that already exists per
`/query` call: FastAPI request span → quota check → SQLAlchemy spans (retrieval) → httpx span
(Anthropic call) → response, carrying `user.tier`/`user.id`/`conversation.id` attributes
(`apps/api/src/openlex_api/routers/query.py`). That data is real today; nothing in Grafana
surfaces it yet.

**Trace Explorer dashboard** (`Engineering` folder):
- Tempo **service graph** panel (API → Postgres → Anthropic, edge latencies/error rates) —
  computed natively from span parent/child relationships, no new instrumentation.
- A **Traces** search panel using TraceQL, with Grafana template variables `$tier` and
  `$conversation_id` bound to the `user.tier`/`conversation.id` span attributes (e.g.
  `{ span.user.tier="$tier" }`). This is where silver/gold/platinum visibility actually lands —
  filter the journey view by tier, per the "visibility only" decision above.
- A **Conversation Traces** table listing every trace matching
  `span.conversation.id="$conversation_id"`, sorted by start time — each turn is its own trace
  (Tempo/Jaeger don't stitch multi-turn sessions into one timeline natively), so this
  reconstructs a conversation's shape (turn count, per-turn latency trend) by letting someone
  click into each turn's full waterfall individually.
- A link-out to the same trace by `trace_id` in the Jaeger UI. Tempo and Jaeger already receive
  the *identical* trace via the Collector's dual OTLP export, so the same `trace_id` opens the
  same trace in either backend — no second correlation scheme needed. This is what answers the
  original "compare traces in Jaeger" concern, once Jaeger is actually reachable (see below).

## Correlation ID: response header

`trace_id` (W3C `traceparent`) is already the sole correlation key by design — it's injected
into `apps/api`'s structured logs (`quota.py`) and identical across Tempo/Jaeger. What's
missing is a way to grab it *from the client side* without already having server-log access.

Fix: extend the existing RED-metrics middleware in `apps/api/src/openlex_api/http_metrics.py`
(it already wraps every request/response uniformly) to also set `X-Trace-Id: <hex trace_id>`
on the response — read the same way `quota.py`'s `_log_quota_event` already does
(`trace.get_current_span().get_span_context()`). One middleware serving two concerns it's
already positioned for, rather than a second middleware layer for one header. Applies to error
responses too (429 quota-exceeded, 404 conversation-not-found), since they still flow through
`call_next`.

**Verification note:** `FastAPIInstrumentor` wraps at the ASGI level, so whether the span is
still current when this middleware's post-`call_next` code runs needs to be live-checked
against a real request — not assumed. Same "prove it, don't assert it" standard the rest of
this stack's implementation already holds itself to.

## Health-check noise

`/healthz` is hit by both k8s liveness and readiness probes continuously, and is currently
excluded from **neither** tracing (`FastAPIInstrumentor` auto-instruments every route with no
exclusion configured) nor the RED metrics middleware (`_EXCLUDED_ROUTES` in `http_metrics.py`
currently only contains `/metrics`) — so it's diluting trace volume and the traffic dashboard
with synthetic probe load right now.

**Decision (industry standard, confirmed): exclude, don't sample.** Two edits:
- `telemetry.py`: `FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz")`
- `http_metrics.py`: add `"/healthz"` to `_EXCLUDED_ROUTES`

Probe *failures* still page via kube-prometheus-stack's default pod-not-ready/crashloop
alerts — nothing new needed there. This only stops synthetic traffic from polluting
application-level traces and dashboards; it does not remove any real failure-detection
capability, since k8s already owns that at the infra layer.

## Anthropic API cost/usage/error instrumentation

Currently zero visibility beyond an unlabeled httpx span: no tokens, no cost, no
model-specific breakdown, and **no exception handling at all** around
`client.messages.create(...)` in `packages/legal_generation/generator.py` — an Anthropic rate
limit and an actual bug both surface as an identical unhandled 500 today.

- Wrap the call in its own span using OTel's **GenAI semantic conventions**
  (`gen_ai.system="anthropic"`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`) rather than inventing custom attribute names.
- New `anthropic_metrics.py` module (mirrors `http_metrics.py`'s existing hand-rolled
  `prometheus_client` pattern — consistent with why that module exists instead of a second OTel
  metrics pipeline, per `telemetry.py`'s own docstring): `openlex_anthropic_requests_total{model,status}`,
  `openlex_anthropic_tokens_total{model,direction}`, `openlex_anthropic_cost_usd_total{model}`
  (from a static per-model pricing table — flagged as needing manual updates when Anthropic
  repricing happens, not a live lookup), `openlex_anthropic_request_duration_seconds`.
- Add a `try/except` around the call catching `anthropic.APIStatusError` subtypes
  (`RateLimitError`, etc.), labeling span/counter `status` as `success` / `rate_limited` /
  `api_error`, then **re-raising unchanged** — pure observability, no retry/behavior change.
  `/query`'s error behavior is identical to today, just now distinguishable in telemetry.
- PII guardrail carried over unchanged from the existing convention: never attribute
  prompt/answer text, only token counts/model/latency/status.

Feeds: Executive's cost trend panel, Engineering's Anthropic latency/error/token row, and
On-Call's error panel (so "Anthropic is throttling us" reads distinctly from "we have a bug"
mid-incident).

## Port-forward / Jaeger access fix

`scripts/observability-port-forward.sh` forwards Grafana, Prometheus, Alertmanager, and the
OTel Collector's OTLP port — but **never forwards Jaeger**, despite the original design doc
explicitly listing it as in scope. This is almost certainly the actual root cause behind "I
can't cross-reference traces in Jaeger": the UI was never reachable, not a problem with the
correlation scheme itself.

Fix: add a `kubectl port-forward` line for Jaeger's query service. The exact service
name/port needs a live `kubectl get svc -n observability | grep jaeger` check during
implementation (the chart runs Jaeger v2's unified collector+query process with no explicit
query-port override in `values-base.yaml` — not guessed here).

## Verification plan

Per this repo's established "prove it, don't assert it" convention:

1. Generate real `/query` traffic across all three tiers → confirm each of the four dashboards
   renders with real (not placeholder) data, and tier filters on the Trace Explorer actually
   narrow results.
2. Force a 500 and a simulated Anthropic rate-limit → confirm both appear distinctly (not as
   the same generic error) on Engineering's Anthropic panel and On-Call's error panel.
3. Pull `X-Trace-Id` off a real `/query` response, paste it into both the Tempo and Jaeger UIs
   (via the now-fixed port-forward script) → same trace opens in both.
4. Confirm `/healthz` traffic (from live liveness/readiness probes) no longer appears in Tempo
   trace search or the Golden Signals traffic panel, while a forced probe failure still fires
   the existing kube-prometheus-stack pod-not-ready alert.
5. Open a real multi-turn conversation → confirm the Conversation Traces table lists one row
   per turn in order, each clicking through to a complete waterfall.
6. Confirm the Anthropic cost counter's cumulative value over a known number of test calls is
   in the right ballpark against the pricing table (sanity check, not exact accounting).

## Phased rollout

1. **Fixes first** (small, unblocks everything else): Jaeger port-forward, health-check
   exclusion, `X-Trace-Id` header. Each independently shippable, each closes a concrete gap
   found in this review.
2. **Anthropic instrumentation**: span + metrics + error classification in `generator.py` and
   the new `anthropic_metrics.py` module. Needed before the Executive cost panel or
   Engineering's Anthropic row have real data to show.
3. **Trace Explorer dashboard**: service graph, TraceQL search with tier/conversation
   variables, Conversation Traces table, Jaeger link-out. Depends on nothing above except the
   port-forward fix (for verification) and existing span attributes (already shipped).
4. **Product & Executive dashboards**: new folders, new panels, plus the one new metric
   (`openlex_query_abstained_total`). Depends on nothing else in this design — could ship in
   parallel with phase 3.
5. **On-Call dashboard**: last, since its alert-linking half-depends on GA checklist item 3.11
   (Alertmanager rules) landing — the dashboard itself can be built and manually verified
   first, with the `dashboard_url` annotation wiring following once 3.11 exists.

Each phase leaves `main` deployable, consistent with the project's global constraint.

## Risks and open questions

| Risk | Resolution |
|---|---|
| Anthropic pricing table is a static, manually-maintained constant | Flagged explicitly in the metrics module rather than silently going stale; a known maintenance item, not a live-lookup dependency |
| Jaeger's exact query-service name/port is unconfirmed from static config alone | Explicit `kubectl get svc` verification step in the implementation plan, not guessed in this doc |
| `X-Trace-Id`'s correctness depends on span-context availability at middleware execution time, which depends on `FastAPIInstrumentor`'s ASGI-level wrapping order | Called out as a live-verification item, same standard the rest of this stack already holds itself to |
| Four dashboards is more to maintain than one | Accepted trade-off — each stays small and legible for its actual audience, rather than one dashboard nobody fully trusts for their purpose |
| On-Call dashboard's alert-linking depends on GA checklist 3.11 (not yet done) | Dashboard itself ships independently in phase 5; alert-link wiring is a small follow-on once 3.11 lands, not a blocker for the dashboard existing |

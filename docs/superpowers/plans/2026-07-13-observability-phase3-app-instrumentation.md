# Observability Phase 3: App-Level OTel Instrumentation + postgres_exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tracing/logging/metrics infrastructure built in the prior two observability
passes actually carry real application data. Right now Tempo/Jaeger/Loki all work and are
proven with manually-sent test spans/logs, but `apps/api` and `apps/worker` don't emit any of
their own traces or use the logging bridge yet — the Golden Signals dashboard's
traffic/error/latency panels are still explicit "pending" placeholders. This phase wires the
OpenTelemetry SDK into both apps (auto-instrumented FastAPI/SQLAlchemy/httpx spans, manual
`user.tier`/`user.id`/`conversation.id` span attributes, a logging bridge that carries
`trace_id`/`span_id` on every log line), deploys `postgres_exporter` for database-level golden
signals, and replaces the dashboard placeholders with real panels now that the data exists.

**Architecture:** Both apps get the OTel Python SDK, configured via
`Settings.otel_exporter_otlp_endpoint` (new, config-driven — never hardcoded, matching the
`cors_allow_origins` precedent already established in this codebase) pointed at the in-cluster
OTel Collector's Service DNS. `apps/api` auto-instruments at FastAPI/SQLAlchemy/httpx
boundaries (near-zero manual code) plus a few manual span attributes at the points request
context becomes known. `apps/worker`, being a one-shot CLI process, must force-flush all
telemetry providers before exit or risk silently losing the last batch — this bit a real
project before (Task 7's original design note) and is called out explicitly per step here.
`postgres_exporter` is a separate, standard Prometheus-native exporter (no OTLP hop) requiring
`pg_stat_statements` enabled at the Postgres server level.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-12-production-observability-design.md`
  (this is that design's originally-scoped Phase 2/3 — backend instrumentation + database
  metrics — the tracing/logging *infrastructure* those phases assumed already exists from the
  two prior passes).
- `OTEL_EXPORTER_OTLP_ENDPOINT` must be config-driven via `Settings`, never hardcoded — same
  precedent as `cors_allow_origins`. Defaults to the in-cluster Collector's Service DNS
  (`http://otel-collector-opentelemetry-collector.observability.svc.cluster.local:4318`,
  confirmed live in Phase 1) so local dev without a Collector doesn't break — the OTel SDK's
  own behavior when the endpoint is unreachable is to drop spans after a timeout, not crash
  the app; confirm this is actually true for the exporter used, don't assume it.
- **PII guardrail** (from the design doc, non-negotiable): never log the raw question/answer
  text at `info` level or attach it as a span attribute — log length/hash only. A legal
  research query can describe someone's actual housing situation.
- `apps/worker` is a one-shot CLI, not a long-running server — every `TracerProvider`/
  `MeterProvider`/`LoggerProvider` must be force-flushed (and ideally shut down) before the
  process exits, or the last ingestion run's telemetry silently never ships. Verify this by
  actually checking a completed ingestion run's trace shows up complete in Tempo/Jaeger, not
  by reading the SDK's docs and assuming it works.
- Verify every OTel Python package's actual API against what's installed (`uv add` resolves a
  real version; check its actual public API via a quick `python -c "import ...; help(...)"` or
  reading the installed package if the initialization pattern is unclear) rather than assuming
  a specific SDK version's API from memory — this project has been bitten by assumed-vs-actual
  schema mismatches in every Helm chart it touched; the same discipline applies to Python
  dependencies.
- Every new/changed Python file passes `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy apps packages`, and its package's existing tests before being considered done.
- `pipelines/` modules aren't an installed package (implicit namespace package, imported
  relative to repo root) — any instrumentation added there follows the same import pattern
  already used in `apps/worker/src/openlex_worker/cli.py` (see its `sys.path` handling).

---

### Task 1: Add OTel SDK dependencies and the `OTEL_EXPORTER_OTLP_ENDPOINT` config field

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/worker/pyproject.toml`
- Modify: `packages/shared/src/openlex_shared/config.py`

**Interfaces:**
- Produces: `settings.otel_exporter_otlp_endpoint: str` (new field, default
  `http://otel-collector-opentelemetry-collector.observability.svc.cluster.local:4318`),
  consumed by Tasks 2 and 5.

- [ ] **Step 1: Add dependencies to both apps**

Run (not hand-edited — let `uv` resolve real, compatible versions):
```bash
uv add --package openlex-api opentelemetry-api opentelemetry-sdk \
  opentelemetry-exporter-otlp-proto-http \
  opentelemetry-instrumentation-fastapi \
  opentelemetry-instrumentation-sqlalchemy \
  opentelemetry-instrumentation-httpx \
  opentelemetry-instrumentation-logging

uv add --package openlex-worker opentelemetry-api opentelemetry-sdk \
  opentelemetry-exporter-otlp-proto-http \
  opentelemetry-instrumentation-httpx \
  opentelemetry-instrumentation-logging
```
Expected: both `uv add` calls succeed and update `apps/api/pyproject.toml`,
`apps/worker/pyproject.toml`, and the root `uv.lock`. If any package name doesn't resolve,
check PyPI for the real current name before proceeding — don't guess a substitute.

- [ ] **Step 2: Add the config field**

Add to `packages/shared/src/openlex_shared/config.py`'s `Settings` class:
```python
    # OTel Collector endpoint for traces/metrics/logs. Config-driven, never hardcoded --
    # same precedent as cors_allow_origins. Defaults to the in-cluster Collector's Service
    # DNS (confirmed live during the observability Phase 1 rollout); override per-environment
    # via .env for local dev against a different Collector, or leave unset if there's no
    # Collector reachable -- the OTLP exporter drops spans after a timeout in that case
    # rather than crashing the app (verify this against the actual installed exporter
    # version before relying on it).
    otel_exporter_otlp_endpoint: str = (
        "http://otel-collector-opentelemetry-collector.observability.svc.cluster.local:4318"
    )
```

- [ ] **Step 3: Verify the workspace still resolves and existing tests pass**

Run:
```bash
uv sync --all-packages
uv run --package openlex-api pytest apps/api/tests -q
uv run --package openlex-shared pytest packages/shared -q 2>&1 | tail -5
```
Expected: all pass (this task adds no behavior yet, just dependencies + one config field).

- [ ] **Step 4: Commit**

```bash
git add apps/api/pyproject.toml apps/worker/pyproject.toml uv.lock packages/shared/src/openlex_shared/config.py
git commit -m "Add OTel SDK dependencies and OTEL_EXPORTER_OTLP_ENDPOINT config"
```

---

### Task 2: Wire OTel SDK initialization and auto-instrumentation into `apps/api`

**Files:**
- Create: `apps/api/src/openlex_api/telemetry.py`
- Modify: `apps/api/src/openlex_api/main.py`

**Interfaces:**
- Consumes: `settings.otel_exporter_otlp_endpoint` (Task 1).
- Produces: `setup_telemetry(app: FastAPI) -> None` — called once from `main.py`'s module
  level (before the `lifespan` context manager runs, so instrumentation is active for the
  very first request) — instruments the FastAPI app, the SQLAlchemy engine, and httpx (for
  the Anthropic SDK's outbound calls), and sets up the OTel logging bridge so every
  `logging.Logger` call carries `trace_id`/`span_id`.

- [ ] **Step 1: Verify the actual OTel SDK initialization API for the installed versions**

Run: `uv run --package openlex-api python -c "from opentelemetry.sdk.trace import TracerProvider; help(TracerProvider)"`
and similarly check `opentelemetry.instrumentation.fastapi.FastAPIInstrumentor`,
`opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor`,
`opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor`,
`opentelemetry.instrumentation.logging.LoggingInstrumentor` — confirm the actual
`instrument()`/`instrument_app()` call signatures for the versions `uv add` resolved in Task
1, since these APIs have changed across major versions historically.

- [ ] **Step 2: Write the telemetry setup module**

```python
# apps/api/src/openlex_api/telemetry.py
"""OpenTelemetry SDK wiring for apps/api: traces (auto-instrumented FastAPI/SQLAlchemy/httpx),
and a logging bridge so every log line carries trace_id/span_id. Config-driven via
settings.otel_exporter_otlp_endpoint (see openlex_shared.config) -- never hardcoded.
"""

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from openlex_shared.config import settings


def setup_telemetry(app: FastAPI) -> None:
    resource = Resource.create({SERVICE_NAME: "openlex-api"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    # SQLAlchemyInstrumentor needs the actual engine, not the class -- wired separately in
    # main.py's lifespan once openlex_shared.db's engine is importable, OR confirm this
    # instrumentor can hook in globally without an engine reference (verify against the
    # actual installed version's API in Step 1 -- don't assume).

    # LoggingInstrumentor injects trace_id/span_id into every stdlib logging.Logger call's
    # format automatically once set_logging_format=True.
    LoggingInstrumentor().instrument(set_logging_format=True)
    logging.getLogger(__name__).info("OpenTelemetry instrumentation initialized")
```

(The SQLAlchemy instrumentation line is deliberately left as a call-out, not prescribed code —
Step 1's verification determines whether it needs the actual `AsyncEngine`/`Engine` object
passed in, which means it may need to move into `main.py`'s `lifespan` after
`openlex_shared.db`'s engine is created, not this module-level function. Resolve this based on
what Step 1 actually found, don't guess.)

- [ ] **Step 3: Wire it into `main.py`**

Modify `apps/api/src/openlex_api/main.py` — add the import and call `setup_telemetry(app)`
right after `app = FastAPI(...)` is constructed (before `app.add_middleware(...)`), adjusting
for whatever Step 2 determined about SQLAlchemy instrumentation's actual requirements.

- [ ] **Step 4: Verify locally against the live Collector**

Start the API (`docker compose up api` or equivalent local run), make one real request (e.g.
`curl localhost:8000/healthz`), and confirm a span shows up in Tempo/Jaeger for it — same
verification pattern as every prior task in this project (query the backend's own API for the
trace, don't just trust the app didn't error).

- [ ] **Step 5: Run the existing test suite and commit**

```bash
uv run --package openlex-api pytest apps/api/tests -q
uv run ruff check apps/api packages/shared
uv run mypy apps/api packages/shared
git add apps/api/src/openlex_api/telemetry.py apps/api/src/openlex_api/main.py
git commit -m "Wire OTel SDK auto-instrumentation into apps/api"
```

---

### Task 3: Add manual span attributes (`user.tier`, `user.id`, `conversation.id`)

**Files:**
- Modify: `apps/api/src/openlex_api/routers/query.py`

**Interfaces:**
- Consumes: `user: User` (already available in the `/query` handler, has `.tier`/`.id`),
  `response: QueryResponse` (already returned by `handle_query_turn`, check whether it carries
  `conversation_id` — it should, per the existing multi-turn chat design).

- [ ] **Step 1: Read the current handler and confirm `QueryResponse`'s fields**

Check `packages/legal_models/src/legal_models/schemas.py`'s `QueryResponse` for a
`conversation_id` field (per ADR-0003's multi-turn chat design, it should have one).

- [ ] **Step 2: Set span attributes at the points they become known**

In `apps/api/src/openlex_api/routers/query.py`'s `query()` handler, after `user` is resolved
(right after the quota check succeeds) and after `handle_query_turn` returns:

```python
from opentelemetry import trace

# ... inside query(), after quota check succeeds:
span = trace.get_current_span()
span.set_attribute("user.tier", user.tier)
span.set_attribute("user.id", str(user.id))

# ... after handle_query_turn returns, before the final return:
span.set_attribute("conversation.id", str(response.conversation_id))
```

**PII guardrail, non-negotiable:** do not set `req.question` or `response.answer` (or any
prefix/substring of them) as a span attribute. If a length signal is useful, `len(req.question)`
is fine; the text itself is not.

- [ ] **Step 3: Verify live — real request shows these attributes on its trace**

Log in as a seeded demo user, make a real `/query` call, find the resulting trace in Tempo or
Jaeger, and confirm `user.tier`/`user.id`/`conversation.id` are present and correct (matching
the actual demo user and conversation used) — not just that `set_attribute` didn't raise.

- [ ] **Step 4: Run tests and commit**

```bash
uv run --package openlex-api pytest apps/api/tests -q
git add apps/api/src/openlex_api/routers/query.py
git commit -m "Add user.tier/user.id/conversation.id span attributes to /query"
```

---

### Task 4: Migrate structured logging to the OTel logging bridge

**Files:**
- Modify: `apps/api/src/openlex_api/quota.py`

**Interfaces:** none new — this changes how `_log_quota_event` emits its existing structured
fields, not what fields it emits.

- [ ] **Step 1: Confirm `LoggingInstrumentor` (Task 2) is already injecting trace context**

Since Task 2 already calls `LoggingInstrumentor().instrument(set_logging_format=True)`, every
`logging.Logger.info(...)` call already gains `trace_id`/`span_id` in its formatted output
without further code changes here — verify this is actually true (check a live log line via
`kubectl logs` shows the injected fields) before assuming `quota.py` needs any change at all.

- [ ] **Step 2: If verification in Step 1 shows the JSON payload itself needs the trace ID
  (not just the surrounding log line format)**

`_log_quota_event`'s `json.dumps({...})` payload is a separate concern from the logging
format string `LoggingInstrumentor` augments — if Loki/Grafana correlation needs `trace_id`
*inside* the JSON body (for structured querying), add it explicitly:

```python
from opentelemetry import trace

def _log_quota_event(...) -> None:
    span = trace.get_current_span()
    trace_id = format(span.get_span_context().trace_id, "032x") if span.get_span_context().is_valid else None
    logger.info(
        json.dumps(
            {
                "event": "query_quota",
                "trace_id": trace_id,
                "user_id": str(user_id),
                ...
            }
        )
    )
```

- [ ] **Step 3: Verify live — a quota log line's `trace_id` matches its request's actual trace**

Make a real `/query` call, find its trace ID in Tempo/Jaeger, then find the corresponding
quota log line in Loki and confirm the `trace_id` field matches exactly.

- [ ] **Step 4: Run tests and commit**

```bash
uv run --package openlex-api pytest apps/api/tests -q
git add apps/api/src/openlex_api/quota.py
git commit -m "Correlate quota event logs with their request trace_id"
```

---

### Task 5: Wire OTel SDK into `apps/worker`, with force-flush before exit

**Files:**
- Create: `apps/worker/src/openlex_worker/telemetry.py`
- Modify: `apps/worker/src/openlex_worker/cli.py`
- Modify: `apps/worker/src/openlex_worker/__main__.py`

**Interfaces:**
- Produces: `setup_telemetry() -> TracerProvider` (returns the provider so `__main__.py` can
  force-flush it before exit), manual spans around each pipeline stage in `run_ingest`
  (normalize→chunk→embed→upsert per document, with `source`/`source_id`/`version`
  attributes — matching the design doc's original Phase 3 spec).

**This is the task most likely to silently fail if done wrong** — a one-shot CLI process that
doesn't force-flush its `TracerProvider` before `sys.exit()` will lose its last (possibly
only) batch of spans, and nothing about a normal test run will reveal this — the process just
exits "successfully" with no telemetry ever having left the box.

- [ ] **Step 1: Write the telemetry setup module**

```python
# apps/worker/src/openlex_worker/telemetry.py
"""OpenTelemetry SDK wiring for apps/worker's one-shot ingestion CLI. Unlike apps/api (a
long-running server), this process must force-flush (not just rely on BatchSpanProcessor's
background export thread) before exit, or the last ingestion run's spans are silently lost --
there is no next request to trigger a flush.
"""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from openlex_shared.config import settings


def setup_telemetry() -> TracerProvider:
    resource = Resource.create({SERVICE_NAME: "openlex-worker"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    return provider
```

- [ ] **Step 2: Add manual spans around each pipeline stage in `run_ingest`**

Modify `apps/worker/src/openlex_worker/cli.py`'s `run_ingest` — wrap the statute/case
ingestion calls in a span per source, and (if `pipelines/indexing/{statutes,cases}.py`'s
per-document upsert loop is reasonably reachable without deep refactoring) a child span per
document with `source`/`source_id`/`version` attributes. If adding per-document spans would
require restructuring `pipelines/indexing/_shared.py`'s write path beyond this task's scope,
scope this down to per-source spans only and note the per-document granularity as a follow-up
— don't force an invasive refactor to hit the original design doc's exact per-document
ambition.

```python
from opentelemetry import trace

_tracer = trace.get_tracer("openlex_worker")

async def run_ingest(
    source: Literal["statutes", "cases", "all"], force: bool = False
) -> IngestResponse:
    results: list[IngestResponse] = []

    if source in ("statutes", "all"):
        with _tracer.start_as_current_span("ingest.statutes") as span:
            span.set_attribute("ingest.force", force)
            async with SessionLocal() as session:
                statute_result = await upsert_all_seed_statutes(session, force=force)
                await session.commit()
            span.set_attribute("ingest.documents_ingested", statute_result.documents_ingested)
            results.append(statute_result)

    if source in ("cases", "all"):
        with _tracer.start_as_current_span("ingest.cases") as span:
            span.set_attribute("ingest.force", force)
            async with SessionLocal() as session:
                case_result = await upsert_all_seed_cases(session, force=force)
                await session.commit()
            span.set_attribute("ingest.documents_ingested", case_result.documents_ingested)
            results.append(case_result)

    # ... rest unchanged
```

- [ ] **Step 3: Wire setup + force-flush into `__main__.py`**

Modify `apps/worker/src/openlex_worker/__main__.py`'s `main()`:

```python
from openlex_worker.telemetry import setup_telemetry

def main() -> None:
    provider = setup_telemetry()
    args = build_parser().parse_args()

    try:
        if args.command == "ingest":
            result = asyncio.run(run_ingest(args.source, force=args.force))
            logger.info("ingest complete: %s", result.model_dump())
            exit_code = 0 if not result.errors else 1
        else:
            _heartbeat_loop()
            exit_code = 0
    finally:
        # Force-flush before exit -- this is a one-shot process, there is no next request to
        # trigger BatchSpanProcessor's background export. A 10s timeout is generous for a
        # handful of spans; if this ever times out in practice, that's worth investigating,
        # not silently swallowing.
        flushed = provider.force_flush(timeout_millis=10_000)
        if not flushed:
            logger.warning("otel_flush_incomplete: some spans may not have been exported")

    sys.exit(exit_code)
```

- [ ] **Step 4: Verify live — a real ingestion run's trace is COMPLETE in Tempo/Jaeger**

Run a real ingestion (`kubectl exec ... python -m openlex_worker ingest --source statutes`),
then find its trace in Tempo/Jaeger and confirm every expected span is present (not just the
first one) — this is the specific failure mode force-flush exists to prevent, so the
verification must actually check for a *complete* trace, not just *a* trace.

- [ ] **Step 5: Run tests and commit**

```bash
uv run --package openlex-worker pytest apps/worker/tests -q
uv run ruff check apps/worker
uv run mypy apps/worker
git add apps/worker/src/openlex_worker/telemetry.py apps/worker/src/openlex_worker/cli.py apps/worker/src/openlex_worker/__main__.py
git commit -m "Wire OTel SDK into apps/worker with force-flush before exit"
```

---

### Task 6: Deploy `postgres_exporter` and enable `pg_stat_statements`

**Files:**
- Modify: `infra/kubernetes/base/postgres/statefulset.yaml`
- Create: `infra/monitoring/postgres-exporter/values-base.yaml`
- Create: `infra/argocd/apps/kind/app-postgres-exporter.yaml`

**Interfaces:**
- Produces: Postgres golden-signal metrics (connections, transaction rate, cache hit ratio,
  slow queries via `pg_stat_statements`) scraped by the already-cluster-wide-scraping
  Prometheus (Phase 1's `serviceMonitorSelectorNilUsesHelmValues: false` fix already covers
  this — no Prometheus config changes needed, only a `ServiceMonitor` for this exporter).

**Per the design doc:** `postgres_exporter` goes in the `openlex` namespace (not
`observability`), so it can reference the existing `openlex-secrets` Secret directly via
`envFrom` — this avoids duplicating DB credentials across namespaces, since Prometheus scrapes
`ServiceMonitor`s across all namespaces already.

- [ ] **Step 1: Enable `pg_stat_statements` on the Postgres server**

Modify `infra/kubernetes/base/postgres/statefulset.yaml` to add
`shared_preload_libraries=pg_stat_statements` to the Postgres container's args/command (check
the current spec for how Postgres is started — likely no custom `command:`, meaning this needs
one added, e.g. `command: ["postgres", "-c", "shared_preload_libraries=pg_stat_statements"]`).
This requires a Postgres restart to take effect (`shared_preload_libraries` can't be reloaded
live) — expect and confirm the StatefulSet rolls.

- [ ] **Step 2: Verify the exact Helm values schema for `prometheus-postgres-exporter`**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo update prometheus-community
helm search repo prometheus-community/prometheus-postgres-exporter --versions | head -3
helm show values prometheus-community/prometheus-postgres-exporter --version "<resolved-version>.*" | grep -B2 -A10 "config:\|datasource\|DATA_SOURCE_NAME"
```
Confirm how to point it at the existing Postgres without duplicating credentials — likely via
`extraEnvSecrets` or `envFromSecret` referencing `openlex-secrets`'s `DATABASE_URL` key, or a
dedicated `DATA_SOURCE_NAME` env var this chart expects. Postgres exporter's expected env var
name may differ from `DATABASE_URL`'s format (`postgresql+asyncpg://...` vs the exporter's
expected plain `postgresql://...` DSN) — check and adapt, don't assume they're interchangeable.

- [ ] **Step 3: Write the values-base file and ArgoCD Application**

Following the same shared-values-base + per-environment-valuesObject pattern as every other
component in this project (destination: `openlex` namespace, not `observability` — this is
the one exception per the design doc's own stated reasoning).

- [ ] **Step 4: Deploy live via `helm upgrade --install` and verify**

Confirm the exporter pod is Running, and query its `/metrics` endpoint directly for
`pg_stat_statements`-derived metrics (e.g. `pg_stat_statements_calls`) — confirm they're
non-empty specifically (not just that generic `pg_up`-style metrics exist), since that's the
proof `pg_stat_statements` is actually active, not just that the exporter itself started.

- [ ] **Step 5: Commit**

```bash
git add infra/kubernetes/base/postgres/statefulset.yaml infra/monitoring/postgres-exporter/values-base.yaml infra/argocd/apps/kind/app-postgres-exporter.yaml
git commit -m "Deploy postgres_exporter and enable pg_stat_statements"
```

---

### Task 7: Replace the Golden Signals dashboard's placeholder panels with real ones

**Files:**
- Modify: `infra/monitoring/grafana/dashboards/golden-signals-api.json`

**Interfaces:** none new — this dashboard already exists (from the Phase 2 follow-up), this
task only replaces its 3 text-placeholder panels.

- [ ] **Step 1: Confirm the real metric names auto-instrumentation produces**

`opentelemetry-instrumentation-fastapi` doesn't itself export Prometheus metrics (traces
only) — traffic/error/latency panels need either OTel *metrics* SDK instrumentation (separate
from the tracing wiring in Task 2) exported via the Collector to Prometheus, or continuing to
rely on `prometheus_client`-style direct metrics. Check what's actually available after Tasks
2-3 land before writing this dashboard — do not write panels against metric names that don't
exist. If no request-duration/count metric exists yet even after this phase (i.e., only traces
were added, not OTel *metrics*), leave the placeholders in place and say so explicitly rather
than closing this task falsely.

- [ ] **Step 2: If real metrics exist, replace the 3 placeholder panels with real timeseries
  panels** using the confirmed real metric names and label sets, following the same panel JSON
  structure as the existing saturation panels in the same file.

- [ ] **Step 3: Verify live — panels show real, non-zero data** from actual `/query` traffic,
  same verification pattern as the original dashboard task.

- [ ] **Step 4: Commit**

```bash
git add infra/monitoring/grafana/dashboards/golden-signals-api.json
git commit -m "Replace Golden Signals placeholder panels with real traffic/error/latency data"
```

## Checkpoint: Phase 3 app instrumentation complete

- [ ] A real `/query` request produces a trace in Tempo/Jaeger spanning auth → quota check →
  retrieval (DB query spans visible) → generation (httpx span to Anthropic) → response
- [ ] That trace's root span carries `user.tier`/`user.id`/`conversation.id`
- [ ] A quota log line in Loki carries the same `trace_id` as its request's trace
- [ ] A real ingestion run's trace in Tempo/Jaeger is complete (every expected span present),
  proving force-flush works
- [ ] `postgres_exporter` metrics include real `pg_stat_statements`-derived data, not just
  generic connection-count metrics
- [ ] Golden Signals dashboard either shows real traffic/error/latency data, or still
  explicitly says what's missing — never a fabricated/empty graph presented as done

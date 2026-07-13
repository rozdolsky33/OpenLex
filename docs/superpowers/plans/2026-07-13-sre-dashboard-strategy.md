# SRE Dashboard Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the approved dashboard-strategy design into working dashboards, fixing two
concrete bugs found along the way (Jaeger never port-forwarded, `/healthz` polluting traces
and RED metrics), adding an `X-Trace-Id` response header, instrumenting the Anthropic API call
(currently zero cost/token/error visibility), and shipping four audience-tiered Grafana
dashboards (Executive, Product, Engineering's Trace Explorer, On-Call).

**Architecture:** Small, independently-shippable fixes first (Tasks 1-4), then the one real
instrumentation gap (Anthropic cost/usage/error, Tasks 5-7), then the four dashboards built on
top of metrics that already exist by that point (Tasks 8-11). Every dashboard task follows the
existing pattern in `infra/monitoring/grafana/dashboards/`: a plain JSON file + a
`kustomization.yaml` entry, no ArgoCD Application changes needed (`app-observability-
dashboards.yaml` already points at the whole `dashboards/` kustomize path).

**Tech Stack:** FastAPI, OpenTelemetry Python SDK (already wired — see
`apps/api/src/openlex_api/telemetry.py`), `prometheus_client` (hand-rolled RED/business
metrics, same pattern as `apps/api/src/openlex_api/http_metrics.py` and
`apps/api/src/openlex_api/quota.py`), Grafana provisioned via `kube-prometheus-stack`'s sidecar
(ConfigMap + `grafana_dashboard: "1"` label, `foldersFromFilesStructure: true`), Tempo + Jaeger
(dual OTLP export from one OTel Collector), all deployed to a local `kind` cluster via ArgoCD.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md`
  (approved, committed at `f03c1de`). This plan implements every section of that spec; do not
  add scope beyond it (e.g. no tier-differentiated SLOs, no browser tracing, no Alertmanager
  rule authoring — all explicitly deferred in the spec).
- Builds on `docs/superpowers/specs/2026-07-12-production-observability-design.md` and its
  implementation, most recently `docs/superpowers/plans/2026-07-13-observability-phase3-app-
  instrumentation.md` — the tracing/metrics/logging infrastructure and existing `Golden Signals
  — API`/`Tier & Quota` dashboards already exist and are not rebuilt here, only extended.
- **PII guardrail** (non-negotiable, carried over unchanged from every prior observability
  pass): never log or attach the raw question/answer text as a span attribute or metric label —
  length/hash only, never content.
- **No behavior change from the Anthropic error-handling addition** (Tasks 5-6): the new
  `try/except` around `client.messages.create` re-raises the original exception unchanged.
  `/query`'s HTTP response behavior for an Anthropic failure must be identical before and after
  this plan — only the telemetry recorded about it changes.
- Verify every third-party API against what's actually installed before writing code against
  it, same discipline as the phase3 plan — this repo has been bitten by assumed-vs-actual
  schema mismatches before. Every claim about `anthropic` SDK exception types and
  `FastAPIInstrumentor`'s `excluded_urls` parameter below has already been verified live against
  the installed versions (`anthropic==0.116.0`, `opentelemetry-instrumentation-fastapi`
  matching this repo's lockfile) — if a future `uv sync` changes these versions, re-verify
  before assuming the code below still matches.
- Jaeger's Service name/port (`svc/jaeger`, port `16686`) and the fact that Tempo/Jaeger/Loki's
  Grafana datasources currently have **no explicit `uid`** (verified via `helm template` against
  the pinned chart versions — see Tasks 1 and 4) are established facts this plan relies on, not
  assumptions.
- Every new/changed Python file passes `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy apps packages`, and its package's existing tests before being considered done.
- This plan does not require a live `kind` cluster to implement or unit-test (all Python tasks
  are mockable; dashboard JSON is written, not deployed, by this plan). Steps marked **"verify
  live"** require a running OpenLex `kind` cluster (`kubectl config current-context` should show
  the OpenLex kind context, not some other project's) — if none is running when a task is
  executed, do the step, note explicitly that live verification was skipped and why, and move
  on. Never claim a live check passed that wasn't actually run.

---

### Task 1: Fix the missing Jaeger port-forward

**Files:**
- Modify: `scripts/observability-port-forward.sh`

**Interfaces:** none — shell script only.

Verified via `helm template jaeger jaegertracing/jaeger --version "4.11.*" -f infra/monitoring/
jaeger/values-base.yaml ...`: the chart's Service is named `jaeger` (matches the ArgoCD
Application's release name) with a `http-query` port `16686` — this is the Jaeger UI/API port,
and it matches what `app-kube-prometheus-stack.yaml`'s Grafana `additionalDataSources` already
assumes (`http://jaeger.observability.svc.cluster.local:16686`).

- [ ] **Step 1: Add the port-forward line**

Modify `scripts/observability-port-forward.sh` — add this block after the existing OTel
Collector port-forward (after line 28, before the ArgoCD comment):

```bash
kubectl port-forward -n "${NAMESPACE}" svc/jaeger 16686:16686 &
pids+=($!)
```

And add its URL to the echo block (after the `OTLP/HTTP` line):

```bash
echo "Jaeger:       http://localhost:16686"
```

- [ ] **Step 2: Verify live (if the OpenLex kind cluster is running)**

```bash
kubectl config current-context
```

If it's the OpenLex kind context: run `scripts/observability-port-forward.sh`, then `curl -sf
http://localhost:16686/ > /dev/null && echo "Jaeger UI reachable"`. If it's a different
project's cluster or no cluster is running, skip this check and say so explicitly rather than
claiming it passed.

- [ ] **Step 3: Commit**

```bash
git add scripts/observability-port-forward.sh
git commit -m "Fix observability-port-forward.sh: Jaeger was never actually forwarded"
```

---

### Task 2: Exclude `/healthz` from tracing and RED metrics

**Files:**
- Modify: `apps/api/src/openlex_api/telemetry.py`
- Modify: `apps/api/src/openlex_api/http_metrics.py`
- Test: `apps/api/tests/test_http_metrics.py` (new)

**Interfaces:**
- Consumes: `_EXCLUDED_ROUTES: frozenset[str]` (existing, in `http_metrics.py`).
- Produces: no new public interface — `/healthz` requests no longer increment
  `HTTP_REQUESTS_TOTAL`/`HTTP_REQUEST_DURATION_SECONDS`, and no longer produce spans.

Verified live: `FastAPIInstrumentor.instrument_app`'s installed signature includes
`excluded_urls: str | None = None` (checked via `uv run --package openlex-api python -c
"from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor; import inspect;
print(inspect.signature(FastAPIInstrumentor.instrument_app))"`).

- [ ] **Step 1: Write the failing test for RED-metrics exclusion**

Create `apps/api/tests/test_http_metrics.py`:

```python
"""Tests for apps/api/src/openlex_api/http_metrics.py's RED-metrics middleware."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from openlex_api.http_metrics import HTTP_REQUESTS_TOTAL
from openlex_api.main import app
from openlex_shared.db import get_session

client = TestClient(app)


def _override_session() -> None:
    async def _get_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _get_session


def _count(route: str) -> float:
    total = 0.0
    for metric in HTTP_REQUESTS_TOTAL.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels.get("route") == route:
                total += sample.value
    return total


def test_healthz_is_excluded_from_red_metrics() -> None:
    _override_session()
    before = _count("/healthz")

    client.get("/healthz")

    assert _count("/healthz") == before
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run it to confirm it currently fails**

```bash
uv run --package openlex-api pytest apps/api/tests/test_http_metrics.py -v
```

Expected: FAIL — `_count("/healthz")` increases by 1, since `/healthz` isn't excluded yet.

- [ ] **Step 3: Add `/healthz` to `_EXCLUDED_ROUTES`**

Modify `apps/api/src/openlex_api/http_metrics.py`:

```python
# Endpoints excluded from these metrics entirely -- /metrics is scraped by Prometheus itself
# every 15-30s, which would otherwise show up as constant synthetic "traffic" unrelated to
# real API usage and pollute the traffic/error-rate panels it's meant to feed. /healthz is
# hit continuously by k8s liveness and readiness probes for the same reason -- industry
# standard is to exclude health-check traffic from application-level RED metrics and rely on
# k8s's own pod-not-ready/crashloop alerting for probe failures (see
# docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md).
_EXCLUDED_ROUTES = frozenset({"/metrics", "/healthz"})
```

- [ ] **Step 4: Run the test again to confirm it passes**

```bash
uv run --package openlex-api pytest apps/api/tests/test_http_metrics.py -v
```

Expected: PASS.

- [ ] **Step 5: Exclude `/healthz` from tracing**

Modify `apps/api/src/openlex_api/telemetry.py` — change the `FastAPIInstrumentor.instrument_app`
call:

```python
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz")
```

Add a one-line note above it explaining why (mirroring the reasoning already added to
`_EXCLUDED_ROUTES`):

```python
    # /healthz is polled continuously by k8s liveness/readiness probes -- excluded from
    # tracing for the same reason it's excluded from http_metrics.py's RED counters (see that
    # module's _EXCLUDED_ROUTES comment): synthetic probe traffic shouldn't dilute trace
    # volume or the traffic dashboard. Probe failures still page via kube-prometheus-stack's
    # default pod-not-ready/crashloop alerts at the k8s level.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz")
```

- [ ] **Step 6: Verify live (if the OpenLex kind cluster is running)**

Hit `/healthz` a few times, then check Tempo/Jaeger trace search for `service.name=openlex-api`
— confirm no `/healthz` spans appear, while a `/query` or `/auth/login` call still produces one.
Skip and say so explicitly if no cluster is running.

- [ ] **Step 7: Run the full apps/api test suite, lint, typecheck, and commit**

```bash
uv run --package openlex-api pytest apps/api/tests -q
uv run ruff check apps/api
uv run mypy apps/api
git add apps/api/src/openlex_api/telemetry.py apps/api/src/openlex_api/http_metrics.py apps/api/tests/test_http_metrics.py
git commit -m "Exclude /healthz from tracing and RED metrics (k8s probe noise)"
```

---

### Task 3: Add the `X-Trace-Id` response header

**Files:**
- Modify: `apps/api/src/openlex_api/http_metrics.py`
- Modify: `apps/api/tests/test_http_metrics.py`

**Interfaces:**
- Produces: every HTTP response from `apps/api` (including 4xx/5xx) carries `X-Trace-Id: <32-
  hex-char trace_id>` when a valid span is active, absent when it isn't (never a fabricated
  value).

- [ ] **Step 1: Write the failing test**

Add to `apps/api/tests/test_http_metrics.py`:

```python
def test_response_carries_x_trace_id_header() -> None:
    _override_session()

    response = client.get("/healthz")

    assert "x-trace-id" in response.headers
    assert len(response.headers["x-trace-id"]) == 32
    int(response.headers["x-trace-id"], 16)  # must be valid hex
    app.dependency_overrides.clear()
```

(Uses `/healthz` deliberately — this header must be set regardless of whether the route is
excluded from *metrics*, since correlation-ID ergonomics matter for every response, not just
metriced ones.)

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run --package openlex-api pytest apps/api/tests/test_http_metrics.py::test_response_carries_x_trace_id_header -v
```

Expected: FAIL — `KeyError` or `assert "x-trace-id" in response.headers` fails.

- [ ] **Step 3: Add the header in the existing RED-metrics middleware**

Modify `apps/api/src/openlex_api/http_metrics.py` — add the import and set the header right
after `call_next` returns, before the route-exclusion check (so it applies to every response,
including excluded routes):

```python
from opentelemetry import trace
```

```python
    @app.middleware("http")
    async def _record_http_metrics(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # Correlation-ID ergonomics: read the same way quota.py's _log_quota_event does, so a
        # caller (support session, curl, browser devtools) can grab this and paste it into
        # either Tempo or Jaeger's "search by trace ID" box without needing server-log access.
        # Applied to every response, including excluded routes below -- this is a debugging
        # aid, not a metric, so it isn't subject to the same noise-reduction exclusion.
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            response.headers["X-Trace-Id"] = format(span_context.trace_id, "032x")

        route = request.scope.get("route")
        route_template = route.path if route is not None else "unmatched"
        if route_template in _EXCLUDED_ROUTES:
            return response
        ...
```

(Keep the rest of the function body — the `status_class`/`HTTP_REQUESTS_TOTAL`/
`HTTP_REQUEST_DURATION_SECONDS` lines — unchanged.)

- [ ] **Step 4: Run the test again to confirm it passes**

```bash
uv run --package openlex-api pytest apps/api/tests/test_http_metrics.py -v
```

Expected: both tests PASS. If `test_response_carries_x_trace_id_header` still fails because
`span_context.is_valid` is `False` in the test client's request context, that means
`FastAPIInstrumentor`'s span isn't active in `TestClient`'s synchronous request path the way it
is for a real server request — investigate whether `setup_telemetry` runs at import time for
the test's `app` instance (it does, in `main.py`) before concluding this is a real gap; do not
weaken the test to hide a real problem.

- [ ] **Step 5: Verify live (if the OpenLex kind cluster is running)**

Make a real `/query` call (e.g. via `apps/web` or `curl` with a valid bearer token), confirm the
response has an `X-Trace-Id` header, and confirm pasting that exact value into Tempo's and
Jaeger's "search by trace ID" fields (via the now-fixed port-forward from Task 1) opens the
same trace in both. This is the concrete fix for the original "compare traces in Jaeger"
complaint — verify it actually works end to end, don't just assert the header exists.

- [ ] **Step 6: Run tests, lint, typecheck, and commit**

```bash
uv run --package openlex-api pytest apps/api/tests -q
uv run ruff check apps/api
uv run mypy apps/api
git add apps/api/src/openlex_api/http_metrics.py apps/api/tests/test_http_metrics.py
git commit -m "Add X-Trace-Id response header for cross-tool correlation"
```

---

### Task 4: Give Tempo/Jaeger/Loki stable Grafana datasource UIDs

**Files:**
- Modify: `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`

**Interfaces:**
- Produces: Grafana datasource UIDs `tempo`, `jaeger`, `loki` (stable, referenceable by
  dashboard JSON — Task 8's Trace Explorer dashboard consumes `uid: tempo` and `uid: jaeger`
  directly).

Verified via `helm template kps prometheus-community/kube-prometheus-stack --version 87.15.2
-f <values with the same additionalDataSources block>`: the rendered `configmaps-datasources
.yaml` shows the built-in `Prometheus`/`Alertmanager` datasources get explicit `uid: prometheus`
/`uid: alertmanager` (matching what `applications/tier-and-quota.json` already hardcodes), but
the three `additionalDataSources` entries (Tempo/Jaeger/Loki) render with **no `uid` field at
all** — Grafana auto-generates one at creation time, which is not `tempo`/`jaeger`/`loki` and
is not guaranteed stable across a datasource re-provision. Any dashboard hardcoding
`"uid": "tempo"` today would silently fail to resolve. This task fixes the root cause instead
of working around it in every dashboard.

- [ ] **Step 1: Add explicit `uid` fields**

Modify `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`'s `additionalDataSources` block
(around line 66-78):

```yaml
            additionalDataSources:
              - name: Tempo
                uid: tempo
                type: tempo
                access: proxy
                url: http://tempo.observability.svc.cluster.local:3200
                isDefault: false
              - name: Jaeger
                uid: jaeger
                type: jaeger
                access: proxy
                url: http://jaeger.observability.svc.cluster.local:16686
                isDefault: false
              - name: Loki
                uid: loki
                type: loki
                access: proxy
                url: http://loki.observability.svc.cluster.local:3100
                isDefault: false
```

- [ ] **Step 2: Re-verify via `helm template` that the UIDs actually apply**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm template kps prometheus-community/kube-prometheus-stack --version "87.15.2" \
  --set grafana.additionalDataSources[0].name=Tempo \
  --set grafana.additionalDataSources[0].uid=tempo \
  --set grafana.additionalDataSources[0].type=tempo \
  --set grafana.additionalDataSources[0].url=http://tempo.observability.svc.cluster.local:3200 \
  --show-only charts/grafana/templates/../templates/configmaps-datasources.yaml 2>/dev/null \
  || echo "adjust --show-only path per the chart's actual template location if this errors"
```

(If `--show-only` can't locate the exact template path, fall back to full `helm template ... |
grep -A3 "uid: tempo"` the same way this plan's authoring verified it — the point is confirming
`uid: tempo`/`uid: jaeger`/`uid: loki` literally appear in the rendered datasource ConfigMap,
not trusting the values file alone.)

- [ ] **Step 3: Verify live (if the OpenLex kind cluster is running)**

If ArgoCD is synced against this branch, confirm `kube-prometheus-stack-grafana-datasource`'s
ConfigMap in the `observability` namespace shows the three explicit UIDs, and that Grafana's
`/api/datasources` endpoint returns `uid: "tempo"` for the Tempo entry. Skip and say so
explicitly if no cluster is running.

- [ ] **Step 4: Commit**

```bash
git add infra/argocd/apps/kind/app-kube-prometheus-stack.yaml
git commit -m "Pin stable Grafana datasource UIDs for Tempo/Jaeger/Loki"
```

---

### Task 5: Anthropic cost/usage metrics module

**Files:**
- Create: `packages/legal_generation/src/legal_generation/anthropic_metrics.py`
- Test: `packages/legal_generation/tests/test_anthropic_metrics.py` (new)

**Interfaces:**
- Produces: `record_anthropic_call(*, model: str, status: str, input_tokens: int,
  output_tokens: int, duration_seconds: float) -> None` — `status` is one of `"success"`,
  `"rate_limited"`, `"api_error"`. Consumed by Task 6. Also exports the four
  `prometheus_client` metric objects (`ANTHROPIC_REQUESTS_TOTAL`, `ANTHROPIC_TOKENS_TOTAL`,
  `ANTHROPIC_COST_USD_TOTAL`, `ANTHROPIC_REQUEST_DURATION_SECONDS`) and
  `ANTHROPIC_PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]]` for dashboards/tests
  to reference by name.

- [ ] **Step 1: Write the failing tests**

Create `packages/legal_generation/tests/test_anthropic_metrics.py`:

```python
"""Tests for legal_generation.anthropic_metrics -- see generator.py for where these are called."""

from legal_generation.anthropic_metrics import (
    ANTHROPIC_COST_USD_TOTAL,
    ANTHROPIC_PRICING_PER_MILLION_TOKENS,
    ANTHROPIC_REQUEST_DURATION_SECONDS,
    ANTHROPIC_REQUESTS_TOTAL,
    ANTHROPIC_TOKENS_TOTAL,
    record_anthropic_call,
)

MODEL = "claude-sonnet-4-5"


def test_record_anthropic_call_success_increments_all_four_metrics() -> None:
    requests_before = ANTHROPIC_REQUESTS_TOTAL.labels(model=MODEL, status="success")._value.get()
    input_tokens_before = ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="input")._value.get()
    output_tokens_before = ANTHROPIC_TOKENS_TOTAL.labels(
        model=MODEL, direction="output"
    )._value.get()
    cost_before = ANTHROPIC_COST_USD_TOTAL.labels(model=MODEL)._value.get()
    duration_count_before = ANTHROPIC_REQUEST_DURATION_SECONDS.labels(
        model=MODEL
    )._sum.get()

    record_anthropic_call(
        model=MODEL, status="success", input_tokens=1000, output_tokens=500, duration_seconds=1.5
    )

    assert ANTHROPIC_REQUESTS_TOTAL.labels(model=MODEL, status="success")._value.get() == (
        requests_before + 1
    )
    assert ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="input")._value.get() == (
        input_tokens_before + 1000
    )
    assert ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="output")._value.get() == (
        output_tokens_before + 500
    )
    input_price, output_price = ANTHROPIC_PRICING_PER_MILLION_TOKENS[MODEL]
    expected_cost = (1000 / 1_000_000) * input_price + (500 / 1_000_000) * output_price
    assert ANTHROPIC_COST_USD_TOTAL.labels(model=MODEL)._value.get() == pytest.approx(
        cost_before + expected_cost
    )
    assert ANTHROPIC_REQUEST_DURATION_SECONDS.labels(model=MODEL)._sum.get() == pytest.approx(
        duration_count_before + 1.5
    )


def test_record_anthropic_call_rate_limited_skips_token_and_cost_counters() -> None:
    tokens_before = ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="input")._value.get()
    cost_before = ANTHROPIC_COST_USD_TOTAL.labels(model=MODEL)._value.get()
    requests_before = ANTHROPIC_REQUESTS_TOTAL.labels(
        model=MODEL, status="rate_limited"
    )._value.get()

    record_anthropic_call(
        model=MODEL, status="rate_limited", input_tokens=0, output_tokens=0, duration_seconds=0.2
    )

    assert ANTHROPIC_REQUESTS_TOTAL.labels(model=MODEL, status="rate_limited")._value.get() == (
        requests_before + 1
    )
    # token/cost counters are meaningless for a call with no usage data -- must not move
    assert ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="input")._value.get() == tokens_before
    assert ANTHROPIC_COST_USD_TOTAL.labels(model=MODEL)._value.get() == cost_before


def test_record_anthropic_call_unknown_model_falls_back_to_default_pricing() -> None:
    from legal_generation.anthropic_metrics import _DEFAULT_PRICING

    cost_before = ANTHROPIC_COST_USD_TOTAL.labels(model="some-future-model")._value.get()

    record_anthropic_call(
        model="some-future-model",
        status="success",
        input_tokens=1_000_000,
        output_tokens=0,
        duration_seconds=1.0,
    )

    expected_cost = cost_before + _DEFAULT_PRICING[0]
    assert ANTHROPIC_COST_USD_TOTAL.labels(model="some-future-model")._value.get() == pytest.approx(
        expected_cost
    )
```

Add `import pytest` at the top of the file (needed for `pytest.approx`).

- [ ] **Step 2: Run the tests to confirm they fail with an import error**

```bash
uv run --package legal-generation pytest packages/legal_generation/tests/test_anthropic_metrics.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'legal_generation.anthropic_metrics'`.

- [ ] **Step 3: Write the module**

Create `packages/legal_generation/src/legal_generation/anthropic_metrics.py`:

```python
"""Prometheus metrics for Anthropic API calls made from generate_answer (see generator.py).

Mirrors apps/api/src/openlex_api/http_metrics.py's hand-rolled prometheus_client pattern --
this project already rejected a second OTel *metrics* pipeline for the same reason
(apps/api/src/openlex_api/telemetry.py's module docstring), so these business-level metrics go
straight to prometheus_client, same as the HTTP RED metrics and quota.py's counters.

ANTHROPIC_PRICING_PER_MILLION_TOKENS is a static, manually-maintained constant -- like
TIER_LIMITS in apps/api/src/openlex_api/quota.py, this is a product-level constant, not
something fetched live. Anthropic's pricing changes over time; revisit this table when it
does -- it will not self-update, and an unrecognized model silently falls back to
_DEFAULT_PRICING rather than raising, so a cost estimate always exists even if imprecise for a
brand-new model this table hasn't been updated for yet.
"""

from prometheus_client import Counter, Histogram

# USD per 1M tokens, as (input_price, output_price). Source: published Anthropic pricing at
# the time this table was last updated (2026-07). No live pricing lookup exists -- update this
# dict by hand when Anthropic reprices.
ANTHROPIC_PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4-5": (15.00, 75.00),
    "claude-haiku-4-5": (0.80, 4.00),
}
_DEFAULT_PRICING: tuple[float, float] = (3.00, 15.00)  # Sonnet-tier fallback for an unrecognized model

ANTHROPIC_REQUESTS_TOTAL = Counter(
    "openlex_anthropic_requests_total",
    "Anthropic messages.create calls by requested model and outcome",
    ["model", "status"],
)
ANTHROPIC_TOKENS_TOTAL = Counter(
    "openlex_anthropic_tokens_total",
    "Anthropic token usage by requested model and direction",
    ["model", "direction"],
)
ANTHROPIC_COST_USD_TOTAL = Counter(
    "openlex_anthropic_cost_usd_total",
    "Estimated Anthropic API cost in USD by requested model, from a static pricing table",
    ["model"],
)
ANTHROPIC_REQUEST_DURATION_SECONDS = Histogram(
    "openlex_anthropic_request_duration_seconds",
    "Anthropic messages.create call duration in seconds by requested model",
    ["model"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30),
)


def record_anthropic_call(
    *, model: str, status: str, input_tokens: int, output_tokens: int, duration_seconds: float
) -> None:
    """Records one Anthropic messages.create call's outcome across all four metrics at once,
    so callers can't update one counter and forget another. `model` is the requested model
    (settings.anthropic_model), not the API's echoed response.model -- keeps label cardinality
    bounded to configured aliases and matches ANTHROPIC_PRICING_PER_MILLION_TOKENS's keys
    exactly, rather than dated model snapshots the pricing table isn't keyed by.
    """
    ANTHROPIC_REQUESTS_TOTAL.labels(model=model, status=status).inc()
    ANTHROPIC_REQUEST_DURATION_SECONDS.labels(model=model).observe(duration_seconds)

    if status != "success":
        return  # token/cost counts are meaningless for a call that never returned usage data

    ANTHROPIC_TOKENS_TOTAL.labels(model=model, direction="input").inc(input_tokens)
    ANTHROPIC_TOKENS_TOTAL.labels(model=model, direction="output").inc(output_tokens)

    input_price, output_price = ANTHROPIC_PRICING_PER_MILLION_TOKENS.get(model, _DEFAULT_PRICING)
    cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    ANTHROPIC_COST_USD_TOTAL.labels(model=model).inc(cost)
```

- [ ] **Step 4: Run the tests again to confirm they pass**

```bash
uv run --package legal-generation pytest packages/legal_generation/tests/test_anthropic_metrics.py -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Lint, typecheck, and commit**

```bash
uv run ruff check packages/legal_generation
uv run mypy packages/legal_generation
git add packages/legal_generation/src/legal_generation/anthropic_metrics.py packages/legal_generation/tests/test_anthropic_metrics.py
git commit -m "Add Anthropic API cost/token/latency metrics module"
```

---

### Task 6: Instrument the Anthropic call in `generate_answer` (span + error classification)

**Files:**
- Modify: `packages/legal_generation/src/legal_generation/generator.py`
- Modify: `packages/legal_generation/tests/test_generator.py`

**Interfaces:**
- Consumes: `record_anthropic_call` (Task 5).
- Produces: no new public interface — `generate_answer`'s signature and return type are
  unchanged; this only adds a span, metrics, and error-status classification around the
  existing `client.messages.create` call.

Verified live (`uv run --package legal-generation python -c "import anthropic, inspect;
print(inspect.signature(anthropic.APIStatusError.__init__)); print(anthropic.RateLimitError
.__mro__)"` against the installed `anthropic==0.116.0`):
`anthropic.RateLimitError` is a subclass of `anthropic.APIStatusError`, constructed as
`RateLimitError(message: str, *, response: httpx.Response, body: object | None)`.

- [ ] **Step 1: Update the shared test mock helper to carry `usage`**

Modify `packages/legal_generation/tests/test_generator.py`'s `_mock_tool_response` — the code
this task adds will read `response.usage.input_tokens`/`.output_tokens` unconditionally on
every successful call, so the existing mock must carry them or every existing test in this
file breaks:

```python
def _mock_tool_response(
    input_dict: dict, *, input_tokens: int = 100, output_tokens: int = 50
) -> SimpleNamespace:
    tool_block = SimpleNamespace(type="tool_use", input=input_dict)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[tool_block], usage=usage)
```

(All 6 existing call sites pass only `input_dict` positionally, so they're unaffected by the
new keyword-only defaults.)

- [ ] **Step 2: Write the failing tests for the new behavior**

Add to `packages/legal_generation/tests/test_generator.py`:

```python
import httpx


async def test_generate_answer_records_anthropic_metrics_on_success() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_tool_response(
        {"abstained": False, "answer": "A tenant is defined as...", "used_chunk_ids": ["chunk-1"]},
        input_tokens=200,
        output_tokens=75,
    )

    with (
        patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client),
        patch("legal_generation.generator.record_anthropic_call") as mock_record,
    ):
        await generate_answer("what is a tenant?", passages=[PASSAGE])

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["status"] == "success"
    assert call_kwargs["input_tokens"] == 200
    assert call_kwargs["output_tokens"] == 75
    assert call_kwargs["duration_seconds"] >= 0


async def test_generate_answer_classifies_rate_limit_and_reraises_unchanged() -> None:
    mock_client = AsyncMock()
    rate_limit_response = httpx.Response(
        429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    mock_client.messages.create.side_effect = anthropic.RateLimitError(
        "rate limited", response=rate_limit_response, body=None
    )

    with (
        patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client),
        patch("legal_generation.generator.record_anthropic_call") as mock_record,
    ):
        with pytest.raises(anthropic.RateLimitError):
            await generate_answer("what is a tenant?", passages=[PASSAGE])

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["status"] == "rate_limited"
    assert call_kwargs["input_tokens"] == 0
    assert call_kwargs["output_tokens"] == 0


async def test_generate_answer_classifies_other_api_errors_and_reraises_unchanged() -> None:
    mock_client = AsyncMock()
    error_response = httpx.Response(
        500, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    mock_client.messages.create.side_effect = anthropic.APIStatusError(
        "server error", response=error_response, body=None
    )

    with (
        patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client),
        patch("legal_generation.generator.record_anthropic_call") as mock_record,
    ):
        with pytest.raises(anthropic.APIStatusError):
            await generate_answer("what is a tenant?", passages=[PASSAGE])

    assert mock_record.call_args.kwargs["status"] == "api_error"
```

Add `import anthropic` and `import pytest` at the top of the test file if not already present
(check first — `anthropic` is imported as `legal_generation.generator.anthropic` inside the
module under test, but these new tests need the real `anthropic` module directly to construct
`anthropic.RateLimitError`/`anthropic.APIStatusError` and to use `pytest.raises`).

- [ ] **Step 3: Run the new tests to confirm they fail**

```bash
uv run --package legal-generation pytest packages/legal_generation/tests/test_generator.py -v -k "anthropic_metrics or rate_limit or other_api_errors"
```

Expected: FAIL — `AttributeError: module 'legal_generation.generator' has no attribute
'record_anthropic_call'` (not yet imported) or the calls succeed without recording anything.

- [ ] **Step 4: Implement the span + error classification + metrics recording**

Modify `packages/legal_generation/src/legal_generation/generator.py`. Add imports at the top:

```python
import time

from opentelemetry import trace

from legal_generation.anthropic_metrics import record_anthropic_call
```

Add a module-level tracer near the existing module-level constants:

```python
_tracer = trace.get_tracer(__name__)
```

Replace the existing call site:

```python
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        tools=[ANSWER_TOOL],
        tool_choice=ToolChoiceToolParam(type="tool", name="provide_answer"),
        messages=cast(list[MessageParam], messages_list),
    )
```

with:

```python
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    start = time.perf_counter()
    with _tracer.start_as_current_span("anthropic.messages.create") as span:
        # GenAI semantic-convention attribute names (gen_ai.*) -- real OTel prior art, not an
        # invented scheme, so this trace waterfall stays legible next to any other GenAI-
        # instrumented service someone might compare it to later.
        span.set_attribute("gen_ai.system", "anthropic")
        span.set_attribute("gen_ai.request.model", settings.anthropic_model)
        try:
            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                tools=[ANSWER_TOOL],
                tool_choice=ToolChoiceToolParam(type="tool", name="provide_answer"),
                messages=cast(list[MessageParam], messages_list),
            )
        except anthropic.APIStatusError as exc:
            # Pure observability -- classify and record, then re-raise the exact original
            # exception unchanged. /query's HTTP error behavior must not change; only what's
            # recorded about the failure changes (see this task's Global Constraints entry).
            status = "rate_limited" if isinstance(exc, anthropic.RateLimitError) else "api_error"
            span.set_attribute("error.type", status)
            record_anthropic_call(
                model=settings.anthropic_model,
                status=status,
                input_tokens=0,
                output_tokens=0,
                duration_seconds=time.perf_counter() - start,
            )
            raise

        span.set_attribute("gen_ai.usage.input_tokens", response.usage.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", response.usage.output_tokens)
        record_anthropic_call(
            model=settings.anthropic_model,
            status="success",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            duration_seconds=time.perf_counter() - start,
        )
```

Everything below this block (`tool_use = next(...)` onward) stays exactly as-is, now inside the
`with` block's indentation level — no other logic changes.

- [ ] **Step 5: Run the new tests to confirm they pass**

```bash
uv run --package legal-generation pytest packages/legal_generation/tests/test_generator.py -v
```

Expected: all tests in the file PASS, including the pre-existing ones (proves `_mock_tool_
response`'s new `usage` field didn't break anything).

- [ ] **Step 6: Verify live (if the OpenLex kind cluster is running and `ANTHROPIC_API_KEY` is
  set)**

Make a real `/query` call, confirm the resulting trace has an `anthropic.messages.create`
child span with `gen_ai.usage.input_tokens`/`gen_ai.usage.output_tokens` set to real,
non-zero values, and that `openlex_anthropic_cost_usd_total` in Prometheus increased by a
plausible amount. Skip and say so explicitly if no cluster/API key is available.

- [ ] **Step 7: Run the full package test suite, lint, typecheck, and commit**

```bash
uv run --package legal-generation pytest packages/legal_generation -q
uv run ruff check packages/legal_generation
uv run mypy packages/legal_generation
git add packages/legal_generation/src/legal_generation/generator.py packages/legal_generation/tests/test_generator.py
git commit -m "Instrument Anthropic API call with GenAI span attributes and cost/error metrics"
```

---

### Task 7: Add the `openlex_query_abstained_total` counter

**Files:**
- Modify: `packages/legal_generation/src/legal_generation/conversation.py`
- Modify: `packages/legal_generation/tests/test_conversation.py`

**Interfaces:**
- Produces: `QUERY_ABSTAINED_TOTAL` (a `prometheus_client.Counter`, no labels), incremented
  once per turn where `response.abstained is True`. Consumed by Task 9's Product & Usage
  dashboard (abstain-rate panel divides this by `openlex_http_requests_total{route="/query",
  status_class="2xx"}`, both already/newly real metrics — no new denominator metric needed).

- [ ] **Step 1: Write the failing tests**

Add to `packages/legal_generation/tests/test_conversation.py`:

```python
from legal_generation.conversation import QUERY_ABSTAINED_TOTAL


async def test_handle_query_turn_increments_abstained_counter_when_response_is_abstained() -> None:
    session = _mock_session_that_assigns_id_on_flush()
    generated = QueryResponse(answer="I don't have enough information...", citations=[], abstained=True)
    before = QUERY_ABSTAINED_TOTAL._value.get()

    with (
        patch(
            "legal_generation.conversation.reformulate_query",
            AsyncMock(side_effect=lambda history, question: question),
        ),
        patch("legal_generation.conversation.hybrid_search", AsyncMock(return_value=[])),
        patch("legal_generation.conversation.generate_answer", AsyncMock(return_value=generated)),
    ):
        await handle_query_turn(session, "an unanswerable question", user_id=uuid.uuid4())

    assert QUERY_ABSTAINED_TOTAL._value.get() == before + 1


async def test_handle_query_turn_does_not_increment_abstained_counter_when_answered() -> None:
    session = _mock_session_that_assigns_id_on_flush()
    generated = QueryResponse(answer="A tenant is defined as...", citations=[], abstained=False)
    before = QUERY_ABSTAINED_TOTAL._value.get()

    with (
        patch(
            "legal_generation.conversation.reformulate_query",
            AsyncMock(side_effect=lambda history, question: question),
        ),
        patch("legal_generation.conversation.hybrid_search", AsyncMock(return_value=[PASSAGE])),
        patch("legal_generation.conversation.generate_answer", AsyncMock(return_value=generated)),
    ):
        await handle_query_turn(session, "what is a tenant?", user_id=uuid.uuid4())

    assert QUERY_ABSTAINED_TOTAL._value.get() == before
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
uv run --package legal-generation pytest packages/legal_generation/tests/test_conversation.py -v -k abstained
```

Expected: FAIL — `ImportError: cannot import name 'QUERY_ABSTAINED_TOTAL'`.

- [ ] **Step 3: Add the counter and increment it**

Modify `packages/legal_generation/src/legal_generation/conversation.py`. Add the import and
counter definition near the top (after the existing imports):

```python
from prometheus_client import Counter
```

```python
QUERY_ABSTAINED_TOTAL = Counter(
    "openlex_query_abstained_total",
    "Turns where generate_answer abstained (hard abstain on empty retrieval, or the "
    "grounded-answer-contract's defense-in-depth abstain) -- see the Product & Usage "
    "dashboard's abstain-rate panel, which divides this by openlex_http_requests_total"
    '{route="/query"}.',
)
```

In `handle_query_turn`, right after `response = await generate_answer(...)`:

```python
    response = await generate_answer(question, passages, history=history)
    if response.abstained:
        QUERY_ABSTAINED_TOTAL.inc()
```

- [ ] **Step 4: Run the tests again to confirm they pass**

```bash
uv run --package legal-generation pytest packages/legal_generation/tests/test_conversation.py -v
```

Expected: all tests in the file PASS.

- [ ] **Step 5: Lint, typecheck, and commit**

```bash
uv run ruff check packages/legal_generation
uv run mypy packages/legal_generation
git add packages/legal_generation/src/legal_generation/conversation.py packages/legal_generation/tests/test_conversation.py
git commit -m "Add openlex_query_abstained_total counter for the Product & Usage dashboard"
```

---

### Task 8: Trace Explorer dashboard

**Files:**
- Create: `infra/monitoring/grafana/dashboards/applications/trace-explorer.json`
- Modify: `infra/monitoring/grafana/dashboards/kustomization.yaml`

**Interfaces:** none new — pure dashboard JSON, consumes the `tempo`/`jaeger` datasource UIDs
from Task 4 and the `user.tier`/`conversation.id` span attributes that already exist (per
`apps/api/src/openlex_api/routers/query.py`).

Lands in the existing `Applications` Grafana folder (not a new "Engineering" folder) —
`Golden Signals — API` and `Tier & Quota` already live there and are exactly this audience; no
value in renaming an established folder for this pass.

- [ ] **Step 1: Write the dashboard JSON**

Create `infra/monitoring/grafana/dashboards/applications/trace-explorer.json`:

```json
{
  "id": null,
  "uid": "openlex-trace-explorer",
  "title": "User Journey / Trace Explorer",
  "description": "Per-request trace waterfalls for /query, filterable by tier and conversation. Tempo is the primary trace source; every panel here also works against Jaeger by switching the datasource, since both receive the identical trace via the OTel Collector's dual export -- see docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md.",
  "tags": ["openlex", "traces", "user-journey"],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "editable": true,
  "refresh": "",
  "time": { "from": "now-1h", "to": "now" },
  "templating": {
    "list": [
      {
        "name": "tier",
        "type": "custom",
        "label": "Tier",
        "query": "silver,gold,platinum",
        "includeAll": true,
        "multi": false,
        "current": { "text": "All", "value": "$__all" }
      },
      {
        "name": "conversation_id",
        "type": "textbox",
        "label": "Conversation ID",
        "query": "",
        "current": { "text": "", "value": "" }
      }
    ]
  },
  "annotations": { "list": [] },
  "panels": [
    {
      "id": 1,
      "type": "nodeGraph",
      "title": "Service graph (API → Postgres → Anthropic)",
      "description": "Tempo's service graph, computed from span parent/child relationships -- no extra instrumentation needed beyond the existing FastAPI/SQLAlchemy/httpx auto-instrumentation.",
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 0 },
      "datasource": { "type": "tempo", "uid": "tempo" },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "tempo", "uid": "tempo" },
          "queryType": "serviceMap"
        }
      ]
    },
    {
      "id": 2,
      "type": "table",
      "title": "Traces (filtered by tier)",
      "description": "TraceQL search over span.user.tier -- set the Tier variable above to narrow to one tier, or leave as All.",
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 10 },
      "datasource": { "type": "tempo", "uid": "tempo" },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "tempo", "uid": "tempo" },
          "queryType": "traceql",
          "limit": 50,
          "query": "{ resource.service.name=\"openlex-api\" && span.user.tier =~ \"${tier:regex}\" }"
        }
      ]
    },
    {
      "id": 3,
      "type": "table",
      "title": "Conversation traces (one row per turn)",
      "description": "Every trace for the Conversation ID entered above, sorted by start time -- each multi-turn conversation is a separate trace per turn (Tempo/Jaeger don't stitch multi-trace sessions into one timeline natively), so this reconstructs a conversation's shape by listing each turn's trace individually. Click a row to open its full waterfall.",
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 20 },
      "datasource": { "type": "tempo", "uid": "tempo" },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "tempo", "uid": "tempo" },
          "queryType": "traceql",
          "limit": 50,
          "query": "{ span.conversation.id=\"${conversation_id}\" }"
        }
      ]
    },
    {
      "id": 4,
      "type": "text",
      "title": "Compare in Jaeger",
      "gridPos": { "h": 4, "w": 24, "x": 0, "y": 30 },
      "options": {
        "mode": "markdown",
        "content": "Tempo and Jaeger receive the **identical trace** from the OTel Collector's dual export -- copy any `trace_id` from the tables above (or from an `X-Trace-Id` response header) and paste it into [Jaeger's search-by-trace-ID](http://localhost:16686/search) (after running `scripts/observability-port-forward.sh`) to open the same trace there."
      }
    }
  ]
}
```

- [ ] **Step 2: Add it to the kustomization**

Modify `infra/monitoring/grafana/dashboards/kustomization.yaml` — add
`applications/trace-explorer.json` to the existing `openlex-grafana-dashboards-applications`
generator's `files` list:

```yaml
  - name: openlex-grafana-dashboards-applications
    files:
      - applications/golden-signals-api.json
      - applications/tier-and-quota.json
      - applications/trace-explorer.json
```

- [ ] **Step 3: Validate the JSON and kustomize output locally**

```bash
python3 -c "import json; json.load(open('infra/monitoring/grafana/dashboards/applications/trace-explorer.json'))" && echo "valid JSON"
kubectl kustomize infra/monitoring/grafana/dashboards | grep -A2 "trace-explorer"
```

Expected: valid JSON, and the kustomize output shows `trace-explorer.json` included in the
generated ConfigMap's data keys.

- [ ] **Step 4: Verify live (if the OpenLex kind cluster is running)**

```bash
kubectl kustomize infra/monitoring/grafana/dashboards | kubectl apply -f -
```

Then in Grafana (via the port-forward from `scripts/observability-port-forward.sh`), confirm
the dashboard appears under the `Applications` folder, the service graph renders after some
real `/query` traffic, and the Tier/Conversation ID filters actually narrow the trace table.
The `nodeGraph`/Tempo `traceql` panel schema is version-sensitive — if a panel renders as a
raw JSON error instead of the expected visualization, that's real information: fix the panel
type/query against what this specific Grafana/Tempo version actually expects, rather than
leaving a broken panel in place. Skip this whole step and say so explicitly if no cluster is
running.

- [ ] **Step 5: Commit**

```bash
git add infra/monitoring/grafana/dashboards/applications/trace-explorer.json infra/monitoring/grafana/dashboards/kustomization.yaml
git commit -m "Add User Journey / Trace Explorer dashboard"
```

---

### Task 9: Product & Usage dashboard

**Files:**
- Create: `infra/monitoring/grafana/dashboards/product/product-and-usage.json`
- Modify: `infra/monitoring/grafana/dashboards/kustomization.yaml`

**Interfaces:** none new — consumes `openlex_query_requests_total` (existing, tiered),
`openlex_query_quota_exceeded_total` (existing, tiered), `openlex_query_abstained_total`
(Task 7), `openlex_http_requests_total{route="/query"}` (existing).

- [ ] **Step 1: Write the dashboard JSON**

Create `infra/monitoring/grafana/dashboards/product/product-and-usage.json`:

```json
{
  "id": null,
  "uid": "openlex-product-and-usage",
  "title": "Product & Usage",
  "description": "Usage-shaped view for product decisions: query volume by tier, abstain rate, and quota-exhaustion frequency. See docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md.",
  "tags": ["openlex", "product"],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "editable": true,
  "refresh": "",
  "time": { "from": "now-7d", "to": "now" },
  "templating": { "list": [] },
  "annotations": { "list": [] },
  "panels": [
    {
      "id": 1,
      "type": "timeseries",
      "title": "Query volume by tier (rate, 1h)",
      "description": "sum by (tier) (rate(openlex_query_requests_total[1h]))",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqph", "custom": { "drawStyle": "line", "fillOpacity": 10, "showPoints": "never" } },
        "overrides": []
      },
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "sum by (tier) (rate(openlex_query_requests_total[1h]))",
          "legendFormat": "{{tier}}"
        }
      ]
    },
    {
      "id": 2,
      "type": "timeseries",
      "title": "Abstain rate (%, 1h)",
      "description": "100 * rate(openlex_query_abstained_total[1h]) / rate(openlex_http_requests_total{route=\"/query\",status_class=\"2xx\"}[1h]) -- share of successful /query calls that abstained rather than answering.",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "percent", "custom": { "drawStyle": "line", "fillOpacity": 10, "showPoints": "never" } },
        "overrides": []
      },
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "100 * rate(openlex_query_abstained_total[1h]) / rate(openlex_http_requests_total{route=\"/query\",status_class=\"2xx\"}[1h])",
          "legendFormat": "abstain rate"
        }
      ]
    },
    {
      "id": 3,
      "type": "timeseries",
      "title": "Quota-exhaustion frequency by tier (rate, 1h)",
      "description": "sum by (tier) (rate(openlex_query_quota_exceeded_total[1h])) -- how often each tier's users hit their quota wall.",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 8 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqph", "custom": { "drawStyle": "line", "fillOpacity": 10, "showPoints": "never" } },
        "overrides": []
      },
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "sum by (tier) (rate(openlex_query_quota_exceeded_total[1h]))",
          "legendFormat": "{{tier}}"
        }
      ]
    },
    {
      "id": 4,
      "type": "stat",
      "title": "Total accepted queries (7d)",
      "description": "sum(increase(openlex_query_requests_total[7d])) by (tier)",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 8 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] },
      "options": {
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "orientation": "horizontal",
        "textMode": "value_and_name",
        "colorMode": "value"
      },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "sum by (tier) (increase(openlex_query_requests_total[7d]))",
          "legendFormat": "{{tier}}",
          "instant": true
        }
      ]
    }
  ]
}
```

(Doc-type mix and conversation-length distribution panels from the design's initial sketch are
deliberately left out: neither `doc_type` nor per-conversation turn count is currently exposed
as a Prometheus label anywhere — adding them would mean a new label on an existing counter or a
new metric, which is out of this task's scope as specced. Noting this explicitly rather than
faking a panel against a metric that doesn't exist.)

- [ ] **Step 2: Add the new `product` folder to the kustomization**

Modify `infra/monitoring/grafana/dashboards/kustomization.yaml` — add a new generator block
(after the `openlex-grafana-dashboards-applications` block):

```yaml
  - name: openlex-grafana-dashboards-product
    files:
      - product/product-and-usage.json
    options:
      annotations:
        grafana_folder: /tmp/dashboards/Product
      labels:
        grafana_dashboard: "1"
```

- [ ] **Step 3: Validate the JSON and kustomize output locally**

```bash
python3 -c "import json; json.load(open('infra/monitoring/grafana/dashboards/product/product-and-usage.json'))" && echo "valid JSON"
kubectl kustomize infra/monitoring/grafana/dashboards | grep -B2 -A2 "grafana_folder: /tmp/dashboards/Product"
```

- [ ] **Step 4: Verify live (if the OpenLex kind cluster is running)**

```bash
kubectl kustomize infra/monitoring/grafana/dashboards | kubectl apply -f -
```

Confirm a new `Product` folder appears in Grafana with this dashboard inside it, and that the
abstain-rate panel shows real (not `NaN`-only) data once some `/query` traffic has flowed
through Task 7's counter. Skip and say so explicitly if no cluster is running.

- [ ] **Step 5: Commit**

```bash
git add infra/monitoring/grafana/dashboards/product/product-and-usage.json infra/monitoring/grafana/dashboards/kustomization.yaml
git commit -m "Add Product & Usage dashboard"
```

---

### Task 10: Executive Overview dashboard

**Files:**
- Create: `infra/monitoring/grafana/dashboards/executive/executive-overview.json`
- Modify: `infra/monitoring/grafana/dashboards/kustomization.yaml`

**Interfaces:** none new — consumes `openlex_http_requests_total` (existing),
`openlex_query_requests_total` (existing, tiered), `openlex_anthropic_cost_usd_total`
(Task 5/6), `openlex_http_request_duration_seconds` (existing).

- [ ] **Step 1: Write the dashboard JSON**

Create `infra/monitoring/grafana/dashboards/executive/executive-overview.json`:

```json
{
  "id": null,
  "uid": "openlex-executive-overview",
  "title": "Executive Overview",
  "description": "Monthly-cadence business-health glance: is the product working, and what does it cost. Not a debugging tool -- see the Engineering/Applications folder for that. docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md.",
  "tags": ["openlex", "executive"],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "editable": true,
  "refresh": "",
  "time": { "from": "now-30d", "to": "now" },
  "templating": { "list": [] },
  "annotations": { "list": [] },
  "panels": [
    {
      "id": 1,
      "type": "stat",
      "title": "Error-free rate, /query + /auth (30d)",
      "description": "100 * (1 - sum(increase(openlex_http_requests_total{route=~\"/query|/auth.*\",status_class=\"5xx\"}[30d])) / sum(increase(openlex_http_requests_total{route=~\"/query|/auth.*\"}[30d]))) -- against the 99% SLO target from the production observability design doc.",
      "gridPos": { "h": 6, "w": 8, "x": 0, "y": 0 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "thresholds": { "mode": "absolute", "steps": [{ "color": "red" }, { "color": "green", "value": 99 }] }
        },
        "overrides": []
      },
      "options": { "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false }, "colorMode": "value" },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "100 * (1 - (sum(increase(openlex_http_requests_total{route=~\"/query|/auth.*\",status_class=\"5xx\"}[30d])) OR on() vector(0)) / sum(increase(openlex_http_requests_total{route=~\"/query|/auth.*\"}[30d])))",
          "instant": true
        }
      ]
    },
    {
      "id": 2,
      "type": "stat",
      "title": "Estimated Anthropic cost (30d)",
      "description": "sum(increase(openlex_anthropic_cost_usd_total[30d])) -- from the static pricing table in legal_generation.anthropic_metrics, not a live billing API.",
      "gridPos": { "h": 6, "w": 8, "x": 8, "y": 0 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": { "defaults": { "unit": "currencyUSD" }, "overrides": [] },
      "options": { "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false }, "colorMode": "value" },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "sum(increase(openlex_anthropic_cost_usd_total[30d]))",
          "instant": true
        }
      ]
    },
    {
      "id": 3,
      "type": "stat",
      "title": "p95 latency, /query (30d)",
      "description": "histogram_quantile(0.95, sum by (le) (rate(openlex_http_request_duration_seconds_bucket{route=\"/query\"}[30d])))",
      "gridPos": { "h": 6, "w": 8, "x": 16, "y": 0 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": { "defaults": { "unit": "s" }, "overrides": [] },
      "options": { "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false }, "colorMode": "value" },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "histogram_quantile(0.95, sum by (le) (rate(openlex_http_request_duration_seconds_bucket{route=\"/query\"}[30d])))",
          "instant": true
        }
      ]
    },
    {
      "id": 4,
      "type": "timeseries",
      "title": "Query volume trend (30d)",
      "description": "sum(rate(openlex_query_requests_total[1d]))",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 6 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqpd", "custom": { "drawStyle": "line", "fillOpacity": 10, "showPoints": "never" } },
        "overrides": []
      },
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "sum(rate(openlex_query_requests_total[1d])) * 86400",
          "legendFormat": "queries/day"
        }
      ]
    },
    {
      "id": 5,
      "type": "piechart",
      "title": "Tier mix (30d)",
      "description": "sum by (tier) (increase(openlex_query_requests_total[30d])) -- share of accepted queries by silver/gold/platinum.",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 6 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] },
      "options": { "legend": { "displayMode": "list", "placement": "right" } },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "sum by (tier) (increase(openlex_query_requests_total[30d]))",
          "legendFormat": "{{tier}}",
          "instant": true
        }
      ]
    }
  ]
}
```

(An "active users" panel from the design's initial sketch is left out: there is no
`user_id`-cardinality-safe metric for distinct active users today — building one correctly,
e.g. via a separate low-cardinality aggregation, is real design work beyond a Grafana query and
is noted here as a follow-up, not silently invented as a fake panel.)

- [ ] **Step 2: Add the new `executive` folder to the kustomization**

Modify `infra/monitoring/grafana/dashboards/kustomization.yaml` — add:

```yaml
  - name: openlex-grafana-dashboards-executive
    files:
      - executive/executive-overview.json
    options:
      annotations:
        grafana_folder: /tmp/dashboards/Executive
      labels:
        grafana_dashboard: "1"
```

- [ ] **Step 3: Validate the JSON and kustomize output locally**

```bash
python3 -c "import json; json.load(open('infra/monitoring/grafana/dashboards/executive/executive-overview.json'))" && echo "valid JSON"
kubectl kustomize infra/monitoring/grafana/dashboards | grep -B2 -A2 "grafana_folder: /tmp/dashboards/Executive"
```

- [ ] **Step 4: Verify live (if the OpenLex kind cluster is running)**

```bash
kubectl kustomize infra/monitoring/grafana/dashboards | kubectl apply -f -
```

Confirm the `Executive` folder and dashboard appear, and that the cost/error-rate/latency stat
panels show real values (not `No data`) once Tasks 5-7's metrics have real traffic behind them.
Skip and say so explicitly if no cluster is running.

- [ ] **Step 5: Commit**

```bash
git add infra/monitoring/grafana/dashboards/executive/executive-overview.json infra/monitoring/grafana/dashboards/kustomization.yaml
git commit -m "Add Executive Overview dashboard"
```

---

### Task 11: On-Call Incident dashboard

**Files:**
- Create: `infra/monitoring/grafana/dashboards/oncall/incident.json`
- Modify: `infra/monitoring/grafana/dashboards/kustomization.yaml`

**Interfaces:** none new — consumes Prometheus's built-in `ALERTS` metric (works today against
kube-prometheus-stack's default infra alerts, e.g. pod-crashlooping, even before GA checklist
item 3.11's custom symptom-based `PrometheusRule`s exist — this dashboard is not blocked on
3.11, it just shows more once 3.11 lands) and `openlex_anthropic_requests_total{status=...}`
(Task 5/6) for the Anthropic-specific error breakdown.

- [ ] **Step 1: Write the dashboard JSON**

Create `infra/monitoring/grafana/dashboards/oncall/incident.json`:

```json
{
  "id": null,
  "uid": "openlex-oncall-incident",
  "title": "On-Call Incident",
  "description": "Sparse, triage-first view for a paged engineer: firing alerts, golden signals clipped to the incident window, and Anthropic-specific error breakdown so a rate-limit reads distinctly from a real bug. Not for browsing -- see docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md. This dashboard does not depend on GA checklist item 3.11 (Alertmanager symptom-based rules) to be useful -- ALERTS already reflects kube-prometheus-stack's default infra alerts; 3.11 adds more rows here once it lands, it doesn't unblock this dashboard's existence.",
  "tags": ["openlex", "oncall", "incident"],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "editable": true,
  "refresh": "30s",
  "time": { "from": "now-30m", "to": "now" },
  "templating": { "list": [] },
  "annotations": { "list": [] },
  "panels": [
    {
      "id": 1,
      "type": "table",
      "title": "Firing alerts",
      "description": "ALERTS{alertstate=\"firing\"} -- every currently-firing alert, infra-level (kube-prometheus-stack defaults) or app-level (once GA checklist 3.11 lands), in one place.",
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 0 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "ALERTS{alertstate=\"firing\"}",
          "instant": true,
          "format": "table"
        }
      ]
    },
    {
      "id": 2,
      "type": "timeseries",
      "title": "Error rate, /query + /auth (last 30m)",
      "description": "sum(rate(openlex_http_requests_total{route=~\"/query|/auth.*\",status_class=\"5xx\"}[5m])) / sum(rate(openlex_http_requests_total{route=~\"/query|/auth.*\"}[5m]))",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 8 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "percentunit", "custom": { "drawStyle": "line", "fillOpacity": 10, "showPoints": "never" } },
        "overrides": []
      },
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "sum(rate(openlex_http_requests_total{route=~\"/query|/auth.*\",status_class=\"5xx\"}[5m])) / sum(rate(openlex_http_requests_total{route=~\"/query|/auth.*\"}[5m]))",
          "legendFormat": "error rate"
        }
      ]
    },
    {
      "id": 3,
      "type": "timeseries",
      "title": "Anthropic call outcomes by status (last 30m)",
      "description": "sum by (status) (rate(openlex_anthropic_requests_total[5m])) -- rate_limited reads distinctly from api_error and success, so an Anthropic-side throttle is never mistaken for an OpenLex bug mid-incident.",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 8 },
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqps", "custom": { "drawStyle": "line", "fillOpacity": 10, "showPoints": "never" } },
        "overrides": []
      },
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "prometheus", "uid": "prometheus" },
          "expr": "sum by (status) (rate(openlex_anthropic_requests_total[5m]))",
          "legendFormat": "{{status}}"
        }
      ]
    },
    {
      "id": 4,
      "type": "table",
      "title": "Slowest /query traces (last 30m)",
      "description": "TraceQL search for the slowest spans in the incident window -- click through to the full waterfall in Tempo.",
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 16 },
      "datasource": { "type": "tempo", "uid": "tempo" },
      "targets": [
        {
          "refId": "A",
          "datasource": { "type": "tempo", "uid": "tempo" },
          "queryType": "traceql",
          "limit": 20,
          "query": "{ resource.service.name=\"openlex-api\" && name=\"POST /query\" } | sort(duration desc)"
        }
      ]
    }
  ]
}
```

- [ ] **Step 2: Add the new `oncall` folder to the kustomization**

Modify `infra/monitoring/grafana/dashboards/kustomization.yaml` — add:

```yaml
  - name: openlex-grafana-dashboards-oncall
    files:
      - oncall/incident.json
    options:
      annotations:
        grafana_folder: /tmp/dashboards/On-Call
      labels:
        grafana_dashboard: "1"
```

- [ ] **Step 3: Validate the JSON and kustomize output locally**

```bash
python3 -c "import json; json.load(open('infra/monitoring/grafana/dashboards/oncall/incident.json'))" && echo "valid JSON"
kubectl kustomize infra/monitoring/grafana/dashboards | grep -B2 -A2 "grafana_folder: /tmp/dashboards/On-Call"
```

- [ ] **Step 4: Verify live (if the OpenLex kind cluster is running)**

```bash
kubectl kustomize infra/monitoring/grafana/dashboards | kubectl apply -f -
```

Confirm the `On-Call` folder and dashboard appear, the firing-alerts table shows real data if
anything is currently firing (or is empty/healthy if not — both are valid states, don't force
one), and the slowest-traces panel populates from real `/query` traffic. Note explicitly that
`dashboard_url` alert-annotation wiring (linking a real Alertmanager page straight to this
dashboard) is out of this task's scope — it depends on GA checklist item 3.11's rules existing
first, as called out in the design spec. Skip this whole step and say so explicitly if no
cluster is running.

- [ ] **Step 5: Commit**

```bash
git add infra/monitoring/grafana/dashboards/oncall/incident.json infra/monitoring/grafana/dashboards/kustomization.yaml
git commit -m "Add On-Call Incident dashboard"
```

## Checkpoint: SRE dashboard strategy complete

- [ ] `scripts/observability-port-forward.sh` forwards Jaeger; `curl localhost:16686` succeeds
  while it's running
- [ ] `/healthz` traffic no longer appears in Tempo/Jaeger trace search or
  `openlex_http_requests_total`, while a forced probe failure still fires kube-prometheus-
  stack's default pod-not-ready alert
- [ ] Every `apps/api` response carries a valid 32-hex-char `X-Trace-Id` header; that value
  opens the same trace in both Tempo and Jaeger
- [ ] Tempo/Jaeger/Loki Grafana datasources have stable `uid: tempo`/`uid: jaeger`/`uid: loki`
- [ ] A real `/query` call's trace has an `anthropic.messages.create` span with real
  `gen_ai.usage.*` attributes; `openlex_anthropic_cost_usd_total` increases by a plausible
  amount; a simulated rate limit shows up labeled `status="rate_limited"`, distinctly from a
  generic `api_error`
- [ ] `openlex_query_abstained_total` increases on a real abstained turn and not on an answered
  one
- [ ] Four dashboards exist and render with real (non-empty, non-placeholder) data: Trace
  Explorer (Applications folder), Product & Usage, Executive Overview, On-Call Incident
- [ ] All Python changes pass `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy apps packages`, and `uv run pytest` (excluding the `evaluation`-marked suite)
- [ ] Every dashboard JSON file is valid JSON and appears in `kubectl kustomize
  infra/monitoring/grafana/dashboards` output under its intended folder annotation

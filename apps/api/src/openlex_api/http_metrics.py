"""Prometheus RED (rate/errors/duration) metrics for every HTTP route on apps/api.

This exists because opentelemetry-instrumentation-fastapi's internal duration histogram
silently no-ops -- it's bound to whatever MeterProvider is globally registered, and this
codebase only ever calls trace.set_tracer_provider (see telemetry.py's module docstring),
never opentelemetry.metrics.set_meter_provider. Wiring a full second OTel metrics pipeline
(MeterProvider + PeriodicExportingMetricReader + exporter) just to get an HTTP histogram would
duplicate packages/legal_generation... no, would duplicate what prometheus_client already does
directly -- and quota.py already exports business-level counters the same way, straight to
the existing /metrics endpoint. This module adds the generic HTTP-level counterpart.
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram

# Endpoints excluded from these metrics entirely -- /metrics is scraped by Prometheus itself
# every 15-30s, which would otherwise show up as constant synthetic "traffic" unrelated to
# real API usage and pollute the traffic/error-rate panels it's meant to feed. /healthz is
# hit continuously by k8s liveness and readiness probes for the same reason -- industry
# standard is to exclude health-check traffic from application-level RED metrics and rely on
# k8s's own pod-not-ready/crashloop alerting for probe failures (see
# docs/superpowers/specs/2026-07-13-sre-dashboard-strategy-design.md).
_EXCLUDED_ROUTES = frozenset({"/metrics", "/healthz"})

HTTP_REQUESTS_TOTAL = Counter(
    "openlex_http_requests_total",
    "HTTP requests by method, route, and status class",
    ["method", "route", "status_class"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "openlex_http_request_duration_seconds",
    "HTTP request duration in seconds by method and route",
    ["method", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def setup_http_metrics(app: FastAPI) -> None:
    """Registers a middleware that records RED metrics for every request.

    `route` is the matched route *template* (e.g. "/query"), read off `request.scope["route"]`
    after `call_next` returns -- Starlette's Router populates that key on the shared scope dict
    while resolving the endpoint, before the handler runs. Using the template instead of the
    raw path keeps the label bounded even if path parameters are added later; a request that
    matches no route (404) falls back to "unmatched" rather than the raw path, which would be
    unbounded (see the security-and-hardening/observability skills' cardinality guidance).
    """

    @app.middleware("http")
    async def _record_http_metrics(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # scope["route"] is only populated by Starlette's Router once routing succeeds, which
        # happens inside call_next -- must be read post-dispatch, not before. Unmatched (404)
        # requests fall back to "unmatched" rather than the raw path, keeping the label bounded.
        route = request.scope.get("route")
        route_template = route.path if route is not None else "unmatched"
        if route_template in _EXCLUDED_ROUTES:
            return response

        status_class = f"{response.status_code // 100}xx"
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, route=route_template, status_class=status_class
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, route=route_template).observe(
            duration
        )

        return response

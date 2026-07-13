"""OpenTelemetry SDK wiring for apps/api: traces (auto-instrumented FastAPI/SQLAlchemy/httpx),
and a logging bridge so every log line carries trace_id/span_id. Config-driven via
settings.otel_exporter_otlp_endpoint (see openlex_shared.config) -- never hardcoded.

SQLAlchemy instrumentation note: `SQLAlchemyInstrumentor().instrument()` (no kwargs) only
monkeypatches `create_engine`/`create_async_engine` so *future* engine-creation calls get
instrumented -- it does not retroactively instrument an engine that already exists. Since
`openlex_shared.db` creates its module-level `engine` at import time (and `openlex_api.main`
imports `openlex_shared.db` before this module gets a chance to run), calling `.instrument()`
with no arguments here would silently no-op for our actual engine. The documented fix for an
already-created `AsyncEngine` is to pass its sync counterpart explicitly:
`SQLAlchemyInstrumentor().instrument(engine=async_engine.sync_engine)` (see the installed
opentelemetry-instrumentation-sqlalchemy==0.64b0 package docstring). That's why
`setup_telemetry` takes an optional `engine` argument instead of doing this instrumentation
unconditionally -- `main.py` passes `openlex_shared.db.engine` in explicitly.
"""

import logging

from fastapi import FastAPI
from openlex_shared.config import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def setup_telemetry(app: FastAPI, engine: AsyncEngine | None = None) -> None:
    """Initialize the OTel SDK and auto-instrument FastAPI/SQLAlchemy/httpx/logging.

    Must be called once, before the app starts serving requests, so instrumentation is active
    for the very first request. `engine` should be `openlex_shared.db.engine` (the module-level
    AsyncEngine) -- see the module docstring for why it must be passed explicitly rather than
    relying on SQLAlchemyInstrumentor's no-args global hook.
    """
    resource = Resource.create({SERVICE_NAME: "openlex-api"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # /healthz is polled continuously by k8s liveness/readiness probes -- excluded from
    # tracing for the same reason it's excluded from http_metrics.py's RED counters (see that
    # module's _EXCLUDED_ROUTES comment): synthetic probe traffic shouldn't dilute trace
    # volume or the traffic dashboard. Probe failures still page via kube-prometheus-stack's
    # default pod-not-ready/crashloop alerts at the k8s level.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz")
    HTTPXClientInstrumentor().instrument()

    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    # LoggingInstrumentor injects trace_id/span_id into every stdlib logging.Logger call's
    # format automatically once set_logging_format=True (this also calls logging.basicConfig(),
    # which is fine here since apps/api has no prior basicConfig call to conflict with).
    LoggingInstrumentor().instrument(set_logging_format=True)
    logger.info("OpenTelemetry instrumentation initialized")

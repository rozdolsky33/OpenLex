"""OpenTelemetry SDK wiring for apps/worker's one-shot ingestion CLI. Unlike apps/api (a
long-running server), this process must force-flush (not just rely on BatchSpanProcessor's
background export thread) before exit, or the last ingestion run's spans are silently lost --
there is no next request to trigger a flush. See __main__.py's `main()` for the force-flush
call this module's return value (the TracerProvider) is used for.

No FastAPI auto-instrumentation here -- apps/worker is a CLI, not a server. But it DOES do the
same three things apps/api does that are worth instrumenting to parity:

- **httpx**: the ingestion pipeline (pipelines/ingestion/ny_legislation/client.py) fetches
  statute text over httpx.
- **SQLAlchemy**: ingestion writes documents/chunks to Postgres through openlex_shared.db's
  engine (async SQLAlchemy) -- without instrumenting it, the ingest.statutes/ingest.cases
  spans have no child DB spans (the "gaps in traces"). Same as apps/api, the already-created
  AsyncEngine must be passed explicitly (see openlex_api.telemetry's SQLAlchemy note), so
  setup_telemetry takes an optional `engine` and __main__ passes openlex_shared.db.engine.
- **logging**: LoggingInstrumentor injects trace_id/span_id into every log line so worker logs
  correlate with the ingestion trace (apps/worker did not have this before).

apps/worker does not import legal_generation/the Anthropic SDK.
"""

from openlex_shared.config import settings
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.util.http import PARAMS_TO_REDACT
from sqlalchemy.ext.asyncio import AsyncEngine

# The NY Open Legislation client (pipelines/ingestion/ny_legislation/client.py) authenticates
# via a `?key=<api-key>` query parameter on every request. HTTPXClientInstrumentor records the
# full request URL as the `http.url` span attribute, redacting it through
# opentelemetry.util.http.redact_url()/redact_query_parameters(), which only masks the query
# params listed in the (otherwise unconfigurable -- there's no env var for it) module-level
# PARAMS_TO_REDACT list. That default list ("AWSAccessKeyId", "Signature", "sig",
# "X-Goog-Signature") does not include "key", so without this line the API key would be
# exported to the tracing backend in plaintext on every ingestion span. Do NOT remove this:
# redact_url() mutates/reads PARAMS_TO_REDACT by reference at call time, so appending here
# (before instrument() is called) is sufficient -- no request_hook or monkeypatch needed.
if "key" not in PARAMS_TO_REDACT:
    PARAMS_TO_REDACT.append("key")


def setup_telemetry(engine: AsyncEngine | None = None) -> tuple[TracerProvider, MeterProvider]:
    """Initialize the OTel SDK for the worker CLI process and return the (TracerProvider,
    MeterProvider) so the caller (`__main__.py`) can `force_flush()` both before the process
    exits -- a one-shot job has no next request to trigger the background export threads, so
    both traces and metrics would otherwise be lost.

    `engine` should be `openlex_shared.db.engine` -- passed explicitly (not via
    SQLAlchemyInstrumentor's no-args global hook) because the engine is already created at
    import time; see the module docstring / openlex_api.telemetry for the full reasoning.
    """
    resource = Resource.create({SERVICE_NAME: "openlex-worker"})

    tracer_provider = TracerProvider(resource=resource)
    span_exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # Metrics: the worker's ingest counters/histograms (see cli.py) are pushed over OTLP to the
    # Collector, which re-exports them for Prometheus (a one-shot batch job can't be scraped).
    metric_exporter = OTLPMetricExporter(
        endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/metrics"
    )
    reader = PeriodicExportingMetricReader(metric_exporter)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    HTTPXClientInstrumentor().instrument()
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    # LoggingInstrumentor(set_logging_format=True) calls logging.basicConfig() with a format
    # that includes trace_id/span_id. __main__ deliberately does NOT call basicConfig itself
    # (basicConfig only configures the root logger once -- a prior call would make this a
    # silent no-op and drop the trace context), so this is the single place logging is set up.
    LoggingInstrumentor().instrument(set_logging_format=True)
    return tracer_provider, meter_provider

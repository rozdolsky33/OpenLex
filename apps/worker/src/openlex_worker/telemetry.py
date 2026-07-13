"""OpenTelemetry SDK wiring for apps/worker's one-shot ingestion CLI. Unlike apps/api (a
long-running server), this process must force-flush (not just rely on BatchSpanProcessor's
background export thread) before exit, or the last ingestion run's spans are silently lost --
there is no next request to trigger a flush. See __main__.py's `main()` for the force-flush
call this module's return value (the TracerProvider) is used for.

No FastAPI/SQLAlchemy auto-instrumentation here -- apps/worker doesn't depend on either
(it's a CLI, not a server; DB access goes through openlex_shared.db's plain AsyncSession, and
there's no request framework). httpx is instrumented because pipelines/ingestion's NY Open
Legislation client and legal_generation's Anthropic SDK calls both go over httpx.
"""

from openlex_shared.config import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_telemetry() -> TracerProvider:
    """Initialize the OTel SDK for the worker CLI process and return the TracerProvider so
    the caller (`__main__.py`) can `force_flush()` it before the process exits."""
    resource = Resource.create({SERVICE_NAME: "openlex-worker"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    return provider

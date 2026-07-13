"""OpenTelemetry SDK wiring for apps/worker's one-shot ingestion CLI. Unlike apps/api (a
long-running server), this process must force-flush (not just rely on BatchSpanProcessor's
background export thread) before exit, or the last ingestion run's spans are silently lost --
there is no next request to trigger a flush. See __main__.py's `main()` for the force-flush
call this module's return value (the TracerProvider) is used for.

No FastAPI/SQLAlchemy auto-instrumentation here -- apps/worker doesn't depend on either
(it's a CLI, not a server; DB access goes through openlex_shared.db's plain AsyncSession, and
there's no request framework). httpx is instrumented because apps/worker's own ingestion
pipeline (pipelines/ingestion/ny_legislation/client.py) makes its NY Open Legislation API
calls over httpx -- apps/worker does not import legal_generation/the Anthropic SDK.
"""

from openlex_shared.config import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.util.http import PARAMS_TO_REDACT

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

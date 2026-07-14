import { WebTracerProvider, BatchSpanProcessor, StackContextManager } from "@opentelemetry/sdk-trace-web";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { DocumentLoadInstrumentation } from "@opentelemetry/instrumentation-document-load";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";

const OTLP_ENDPOINT = import.meta.env.VITE_OTLP_ENDPOINT;
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/** Escapes regex metacharacters in a fixed string so it can be used as a literal-match
 * prefix in a RegExp -- API_BASE_URL contains "://" and ":", both regex-significant. */
function escapeForRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Sets up browser tracing: a root span per page load (DocumentLoadInstrumentation) and a
 * child span per fetch() call (FetchInstrumentation), exported via OTLP/HTTP to the
 * Collector. Call once at app startup, before rendering -- see main.tsx.
 *
 * If VITE_OTLP_ENDPOINT isn't set (e.g. a plain `npm run dev` outside the kind overlay,
 * which doesn't inject it), tracing is silently skipped rather than erroring -- this matches
 * apps/api's own precedent of never hardcoding the Collector endpoint and staying usable
 * without one.
 */
export function setupTelemetry(): void {
  if (!OTLP_ENDPOINT) {
    return;
  }

  const provider = new WebTracerProvider({
    resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "openlex-web" }),
    spanProcessors: [
      new BatchSpanProcessor(new OTLPTraceExporter({ url: `${OTLP_ENDPOINT}/v1/traces` })),
    ],
  });

  // StackContextManager, not ZoneContextManager -- no zone.js polyfill needed. Sufficient for
  // this app's fetch-call-shaped instrumentation; revisit only if async context is observed
  // getting lost across a boundary StackContextManager doesn't track (documented OTel Web SDK
  // trade-off, not something this app has hit).
  provider.register({ contextManager: new StackContextManager() });

  registerInstrumentations({
    tracerProvider: provider,
    instrumentations: [
      new DocumentLoadInstrumentation(),
      new FetchInstrumentation({
        // Only inject traceparent into requests to our own API -- never to arbitrary
        // third-party fetches a future feature might add, which would both leak internal
        // trace context and fail CORS preflight on origins that were never configured for it.
        propagateTraceHeaderCorsUrls: [new RegExp(`^${escapeForRegExp(API_BASE_URL)}`)],
      }),
    ],
  });
}

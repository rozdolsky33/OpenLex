/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  /** OTel Collector's OTLP/HTTP base endpoint (e.g. http://localhost:4318), no trailing
   * /v1/traces -- see src/telemetry.ts. Optional: unset means tracing is skipped, not an
   * error (see telemetry.ts's own note on why). */
  readonly VITE_OTLP_ENDPOINT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

import asyncio
import logging
import sys
import time

from openlex_shared.config import settings
from openlex_shared.db import engine

from openlex_worker.cli import build_parser, run_ingest
from openlex_worker.telemetry import setup_telemetry

# No logging.basicConfig() here on purpose: setup_telemetry()'s
# LoggingInstrumentor(set_logging_format=True) owns root-logger config so every line carries
# trace_id/span_id. basicConfig only configures once, so calling it here would make that a
# no-op and drop the trace context. setup_telemetry() runs first thing in main(), before any
# logging happens.
logger = logging.getLogger("openlex_worker")

HEARTBEAT_INTERVAL_SECONDS = 60


def _heartbeat_loop() -> None:
    logger.info(
        "openlex-worker starting (database_url set: %s, anthropic_api_key set: %s)",
        bool(settings.database_url),
        bool(settings.anthropic_api_key),
    )
    while True:
        logger.info("heartbeat: worker alive, no scheduled ingestion wired up yet")
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)


def main() -> None:
    # This is a one-shot CLI process (unlike apps/api's long-running server) -- there is no
    # next request to trigger BatchSpanProcessor's background export thread, so the
    # TracerProvider returned here must be force-flushed before exit (see the `finally` below)
    # or the last ingestion run's spans are silently lost.
    provider = setup_telemetry(engine=engine)
    args = build_parser().parse_args()
    exit_code = 0

    try:
        if args.command == "ingest":
            result = asyncio.run(run_ingest(args.source, force=args.force))
            logger.info("ingest complete: %s", result.model_dump())
            exit_code = 0 if not result.errors else 1
        else:
            # No args (e.g. `docker compose up worker`'s CMD) -- keep the container alive.
            # _heartbeat_loop() runs forever in production (only exited by an external
            # signal), so it never falls through to sys.exit() below -- preserve that (the
            # `return` here matches the pre-existing behavior of this branch, which never
            # called sys.exit).
            _heartbeat_loop()
            return
    finally:
        # A 10s timeout is generous for a handful of spans; if this ever times out in
        # practice, that's worth investigating, not silently swallowing.
        flushed = provider.force_flush(timeout_millis=10_000)
        if not flushed:
            logger.warning("otel_flush_incomplete: some spans may not have been exported")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

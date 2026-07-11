import asyncio
import logging
import sys
import time

from openlex_shared.config import settings

from openlex_worker.cli import build_parser, run_ingest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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


if __name__ == "__main__":
    args = build_parser().parse_args()

    if args.command == "ingest":
        result = asyncio.run(run_ingest(args.source, force=args.force))
        logger.info("ingest complete: %s", result.model_dump())
        sys.exit(0 if not result.errors else 1)
    else:
        # No args (e.g. `docker compose up worker`'s CMD) -- keep the container alive.
        _heartbeat_loop()

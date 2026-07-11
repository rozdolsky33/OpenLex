import logging
import time

from openlex_shared.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("openlex_worker")

HEARTBEAT_INTERVAL_SECONDS = 60

if __name__ == "__main__":
    logger.info(
        "openlex-worker starting (database_url set: %s, anthropic_api_key set: %s)",
        bool(settings.database_url),
        bool(settings.anthropic_api_key),
    )
    while True:
        logger.info("heartbeat: worker alive, no scheduled ingestion wired up yet")
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)

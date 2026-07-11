"""Ingestion CLI: `python -m openlex_worker ingest --source {statutes|cases|all}` (see
scripts/ingest.sh). No CLI framework is a dependency anywhere in this repo -- stdlib
argparse is enough for one subcommand and two flags.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Literal

# pipelines/ has no pyproject.toml -- it's a plain directory (Python implicit namespace
# package) imported relative to the repo root, not an installed workspace package (see
# CLAUDE.md). This isn't automatically on sys.path when running from apps/worker's working
# directory (e.g. `docker compose exec worker python -m openlex_worker ...`).
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from legal_models.schemas import IngestResponse  # noqa: E402
from openlex_shared.db import SessionLocal  # noqa: E402
from pipelines.indexing.statutes import upsert_all_seed_statutes  # noqa: E402

logger = logging.getLogger("openlex_worker")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openlex_worker")
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser("ingest", help="Run the ingestion pipeline")
    ingest_parser.add_argument("--source", choices=["statutes", "cases", "all"], default="all")
    ingest_parser.add_argument("--force", action="store_true")

    return parser


async def run_ingest(
    source: Literal["statutes", "cases", "all"], force: bool = False
) -> IngestResponse:
    results: list[IngestResponse] = []

    if source in ("statutes", "all"):
        async with SessionLocal() as session:
            statute_result = await upsert_all_seed_statutes(session, force=force)
            await session.commit()
        results.append(statute_result)

    if source in ("cases", "all"):
        # No seed_cases.json yet (pipelines/ingestion/ny_case_law/ -- hand-curated, separate
        # later work). A clean no-op, not an error.
        logger.info("no seed_cases.json yet -- skipping case-law ingestion")
        results.append(
            IngestResponse(status="skipped", documents_ingested=0, chunks_created=0, errors=[])
        )

    all_errors = [e for r in results for e in r.errors]
    if source == "cases":
        overall_status = "skipped"
    else:
        overall_status = "partial_failure" if all_errors else "ok"

    return IngestResponse(
        status=overall_status,
        documents_ingested=sum(r.documents_ingested for r in results),
        chunks_created=sum(r.chunks_created for r in results),
        errors=all_errors,
    )

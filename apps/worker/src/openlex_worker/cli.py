"""Ingestion CLI: `python -m openlex_worker ingest --source {statutes|cases|all}` (see
scripts/compose/ingest.sh). No CLI framework is a dependency anywhere in this repo -- stdlib
argparse is enough for one subcommand and two flags.
"""

import argparse
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from opentelemetry import metrics, trace

# pipelines/ has no pyproject.toml -- it's a plain directory (Python implicit namespace
# package) imported relative to the repo root, not an installed workspace package (see
# CLAUDE.md). This isn't automatically on sys.path when running from apps/worker's working
# directory (e.g. `docker compose exec worker python -m openlex_worker ...`).
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from legal_models.schemas import IngestResponse  # noqa: E402
from openlex_shared.db import SessionLocal  # noqa: E402
from pipelines.indexing.cases import upsert_all_seed_cases  # noqa: E402
from pipelines.indexing.statutes import upsert_all_seed_statutes  # noqa: E402

logger = logging.getLogger("openlex_worker")
_tracer = trace.get_tracer("openlex_worker")

# Ingestion run metrics, pushed over OTLP -> Collector -> Prometheus (see telemetry.py). The
# meter/instrument proxies bind to the real MeterProvider once setup_telemetry() sets it, so
# creating them at import time (before setup) is fine -- same pattern as _tracer above. Dotted
# OTel names become prometheus_snake_case with a `_total` counter suffix
# (openlex.ingest.runs -> openlex_ingest_runs_total).
_meter = metrics.get_meter("openlex_worker")
_ingest_runs = _meter.create_counter(
    "openlex.ingest.runs", unit="1", description="Ingestion runs, labeled by source and status"
)
_ingest_documents = _meter.create_counter(
    "openlex.ingest.documents", unit="1", description="Documents ingested, by source"
)
_ingest_chunks = _meter.create_counter(
    "openlex.ingest.chunks", unit="1", description="Chunks created, by source"
)
_ingest_duration = _meter.create_histogram(
    "openlex.ingest.duration", unit="s", description="Ingestion run duration, by source"
)


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
    """Per-source spans only (ingest.statutes / ingest.cases): pipelines/indexing/
    {statutes,cases}.py's per-document upsert loop only returns an aggregate IngestResponse
    (no per-document source_id/version is surfaced to this caller), so per-document child
    spans would require changing those modules' signatures -- out of scope for this task's
    file list (telemetry.py/cli.py/__main__.py only). See the observability Phase 3 plan's
    Task 5 for the explicit scope-down; per-document granularity is a documented follow-up.
    """
    results: list[IngestResponse] = []

    async def _run_one(name: str, upsert: Callable[..., Awaitable[IngestResponse]]) -> None:
        start = time.monotonic()
        with _tracer.start_as_current_span(f"ingest.{name}") as span:
            span.set_attribute("ingest.force", force)
            async with SessionLocal() as session:
                result = await upsert(session, force=force)
                await session.commit()
            span.set_attribute("ingest.documents_ingested", result.documents_ingested)
            span.set_attribute("ingest.chunks_created", result.chunks_created)
        attrs = {"source": name}
        _ingest_duration.record(time.monotonic() - start, attrs)
        _ingest_documents.add(result.documents_ingested, attrs)
        _ingest_chunks.add(result.chunks_created, attrs)
        _ingest_runs.add(1, {**attrs, "status": "partial_failure" if result.errors else "ok"})
        results.append(result)

    if source in ("statutes", "all"):
        await _run_one("statutes", upsert_all_seed_statutes)
    if source in ("cases", "all"):
        await _run_one("cases", upsert_all_seed_cases)

    all_errors = [e for r in results for e in r.errors]
    overall_status = "partial_failure" if all_errors else "ok"

    return IngestResponse(
        status=overall_status,
        documents_ingested=sum(r.documents_ingested for r in results),
        chunks_created=sum(r.chunks_created for r in results),
        errors=all_errors,
    )

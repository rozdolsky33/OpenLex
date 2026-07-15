"""Checks whether any of the seeded statute sections' live activeDate has changed since they
were last ingested -- a signal that the golden-question answers graded against the stored
snapshot might need review. See docs/decisions/0004-golden-question-report-and-pages.md.

Run from the repo root:
`uv run --package openlex-api python scripts/eval/check_statute_freshness.py`
Writes FRESHNESS_RESULTS_PATH (default freshness-results.json). One bad live fetch is recorded
per-section, not fatal to the rest of the batch (mirrors
pipelines/indexing/statutes.py::upsert_all_seed_statutes's per-document error handling) -- a
transient NY Open Legislation API hiccup shouldn't take down the whole check.
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# pipelines/ has no pyproject.toml -- it's a plain directory (Python implicit namespace
# package) imported relative to the repo root, not an installed workspace package (see
# CLAUDE.md and apps/worker/src/openlex_worker/cli.py, which does the same thing).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from legal_models.orm import Document  # noqa: E402
from openlex_shared.db import SessionLocal  # noqa: E402
from pipelines.ingestion.ny_legislation.client import (  # noqa: E402
    _REQUEST_DELAY_SECONDS,
    fetch_law_document,
    load_seed_statutes,
)
from sqlalchemy import select  # noqa: E402


async def _latest_document(session, source_id: str) -> Document | None:
    # Same query shape as pipelines/indexing/statutes.py::_latest_existing.
    stmt = (
        select(Document)
        .where(Document.source == "ny_open_legislation", Document.source_id == source_id)
        .order_by(Document.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def check_all_sections() -> dict[str, Any]:
    sections: list[dict[str, Any]] = []

    async with SessionLocal() as session, httpx.AsyncClient() as client:
        for entry in load_seed_statutes():
            source_id = f"{entry['lawId']}/{entry['locationId']}"
            citation = f"{entry['citationAbbrev']} § {entry['locationId']}"

            document = await _latest_document(session, source_id)
            if document is None:
                sections.append(
                    {
                        "citation": citation,
                        "source_id": source_id,
                        "stored_active_date": None,
                        "live_active_date": None,
                        "changed": None,
                        "error": "not yet ingested",
                    }
                )
                continue

            stored_active_date = document.raw_snapshot.get("activeDate")
            try:
                live_result = await fetch_law_document(client, entry["lawId"], entry["locationId"])
                live_active_date = live_result.get("activeDate")
                sections.append(
                    {
                        "citation": citation,
                        "source_id": source_id,
                        "stored_active_date": stored_active_date,
                        "live_active_date": live_active_date,
                        "changed": stored_active_date != live_active_date,
                        "error": None,
                    }
                )
            except Exception as exc:  # collected per-section, not fatal to the batch
                sections.append(
                    {
                        "citation": citation,
                        "source_id": source_id,
                        "stored_active_date": stored_active_date,
                        "live_active_date": None,
                        "changed": None,
                        "error": str(exc),
                    }
                )

            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

    return {"checked_at": datetime.now(UTC).isoformat(), "sections": sections}


def _report(payload: dict[str, Any]) -> None:
    changed = [s for s in payload["sections"] if s["changed"]]
    errored = [s for s in payload["sections"] if s["error"]]
    total = len(payload["sections"])
    print(f"Checked {total} sections: {len(changed)} changed, {len(errored)} errored.")
    for s in changed:
        print(f"  CHANGED: {s['citation']} ({s['stored_active_date']} -> {s['live_active_date']})")
    for s in errored:
        print(f"  ERROR: {s['citation']}: {s['error']}")


if __name__ == "__main__":
    result = asyncio.run(check_all_sections())

    # File I/O deliberately happens here, outside the async function -- ruff's ASYNC240 flags
    # blocking pathlib calls inside async def, and there's no need for this one-shot script to
    # pull in an async file-I/O library just to satisfy it.
    results_path = Path(os.environ.get("FRESHNESS_RESULTS_PATH", "freshness-results.json"))
    results_path.write_text(json.dumps(result, indent=2))

    _report(result)

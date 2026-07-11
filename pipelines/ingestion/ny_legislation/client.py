"""Client for the NY Open Legislation API (https://legislation.nysenate.gov/api/3/).

Verified live against the real API on 2026-07-10 with a valid key:
  GET /api/3/laws/{lawId}/{locationId}?key=...
returns {"success": bool, "result": {"lawId", "locationId", "title", "docType",
"activeDate", "text", "parents": [...]}}.

Note: the API's internal lawId codes do not match common legal citation
abbreviations -- RPAPL is lawId "RPA", RPL is lawId "RPP", GOL is lawId "GOB".
`seed_statutes.json` carries an explicit `citationAbbrev` per entry so the
human-readable citation shown to users doesn't depend on the API's internal id.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from openlex_shared.config import settings

SEED_STATUTES_PATH = Path(__file__).parent / "seed_statutes.json"

# Be polite to a free public API -- throttle sequential requests.
_REQUEST_DELAY_SECONDS = 1.0


def load_seed_statutes() -> list[dict[str, str]]:
    return json.loads(SEED_STATUTES_PATH.read_text())


async def fetch_law_document(
    client: httpx.AsyncClient, law_id: str, location_id: str
) -> dict[str, Any]:
    url = f"{settings.ny_open_leg_base_url}/laws/{law_id}/{location_id}"
    resp = await client.get(url, params={"key": settings.ny_open_leg_api_key}, timeout=30.0)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(
            f"NY Open Legislation API error for {law_id}/{location_id}: {body.get('message')}"
        )
    return body["result"]


async def fetch_all_seed_statutes() -> list[dict[str, Any]]:
    """Fetch every statute listed in seed_statutes.json, sequentially with throttling."""
    entries = load_seed_statutes()
    results = []
    async with httpx.AsyncClient() as client:
        for entry in entries:
            result = await fetch_law_document(client, entry["lawId"], entry["locationId"])
            result["_citationAbbrev"] = entry["citationAbbrev"]
            results.append(result)
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
    return results

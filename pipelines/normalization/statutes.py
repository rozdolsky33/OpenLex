"""Normalize raw NY Open Legislation API results (pipelines/ingestion/ny_legislation) into
legal_models.Document-shaped data. Kept separate from Document construction itself so this
stays a pure function, easy to unit test against a captured fixture without a DB.
"""

import re
from datetime import date, datetime
from typing import Any

from openlex_shared.config import settings


def _parse_active_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _clean_statute_text(text: str) -> str:
    """The NY Open Legislation API's `text` field embeds literal two-character `\\n`
    sequences as its internal line-wrap marker -- not real newline characters (verified
    against tests/fixtures/rpapl_711_raw.json: zero real newline chars, 100+ literal
    backslash-n substrings). Left as-is, these show up verbatim in citation snippets shown to
    users, and corrupt word-boundary tokenization downstream (`"tenant\\nshall"` counts as one
    word for chunking/full-text search, not two). Collapse them -- and any resulting run of
    whitespace -- to a single space; these are mid-sentence wrap points, not paragraph breaks."""
    return re.sub(r"\s+", " ", text.replace("\\n", " ")).strip()


def normalize_statute(raw: dict[str, Any]) -> dict[str, Any]:
    """`raw` is one element of `fetch_all_seed_statutes()`'s return list -- the NY API's
    `result` dict plus an injected `_citationAbbrev` (see ny_legislation/client.py).

    Returns a dict shaped for Document construction (not yet an ORM instance) plus a `text`
    key (not a Document column -- passed through separately to chunking).
    """
    law_id = raw["lawId"]
    location_id = raw["locationId"]
    citation_abbrev = raw["_citationAbbrev"]

    return {
        "source": "ny_open_legislation",
        "doc_type": "statute",
        "jurisdiction": "NY",
        # Human-readable citation is built from citationAbbrev, never the API's internal
        # lawId -- see the ny-open-legislation-api skill.
        "citation": f"{citation_abbrev} § {location_id}",
        "title": raw.get("title"),
        # source_id is an internal dedup/versioning key (unique with `source`, `version`),
        # not user-facing -- uses the API's own lawId/locationId.
        "source_id": f"{law_id}/{location_id}",
        "effective_date": _parse_active_date(raw.get("activeDate")),
        # Immutable raw snapshot: store exactly what was fetched (including the injected
        # _citationAbbrev) so re-parsing later never requires re-fetching.
        "raw_snapshot": raw,
        "url": f"{settings.ny_open_leg_base_url}/laws/{law_id}/{location_id}",
        "text": _clean_statute_text(raw["text"]),
    }

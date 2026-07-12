"""Normalize hand-curated case-law seed entries (pipelines/ingestion/ny_case_law) into
legal_models.Document-shaped data. Mirrors pipelines/normalization/statutes.py's contract
exactly (pure function, same output key set) except there is no live-fetch step upstream --
see ADR-0006. Kept separate from Document construction itself for the same reason as
normalize_statute: a pure function is easy to unit test against a fixture without a DB.
"""

from datetime import date, datetime
from typing import Any


def _parse_decision_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_case(raw: dict[str, Any]) -> dict[str, Any]:
    """`raw` is one element of `load_seed_cases()`'s return list -- a hand-curated seed entry
    from ny_case_law/seed_cases.json (see loader.py's docstring). Unlike normalize_statute,
    `raw` itself IS the raw snapshot: there's no separate fetched payload to distinguish it
    from (see ADR-0006).

    Returns a dict shaped for Document construction (not yet an ORM instance) plus a `text`
    key (not a Document column -- passed through separately to chunking).
    """
    return {
        "source": "courtlistener_seed",
        "doc_type": "case",
        "jurisdiction": "NY",
        "citation": raw["citation"],
        "title": raw.get("title"),
        # source_id is an internal dedup/versioning key (unique with `source`, `version`),
        # not user-facing -- the CourtListener cluster id uniquely identifies this case.
        "source_id": str(raw["courtlistener_cluster_id"]),
        # effective_date is a statute concept (when a law took effect) -- doesn't apply to
        # case law, decision_date is the equivalent, carried separately below.
        "effective_date": None,
        "decision_date": _parse_decision_date(raw.get("decision_date")),
        "court": raw.get("court"),
        # Immutable raw snapshot: the seed entry itself, verbatim (see module docstring).
        "raw_snapshot": raw,
        "url": raw.get("url"),
        "text": raw["text"],
    }

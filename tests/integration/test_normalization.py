import json
from datetime import date
from pathlib import Path

from pipelines.normalization.statutes import normalize_statute

FIXTURE = Path(__file__).parent.parent / "fixtures" / "rpapl_711_raw.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_normalize_statute_builds_human_readable_citation_from_citation_abbrev() -> None:
    normalized = normalize_statute(_load_fixture())
    assert normalized["citation"] == "RPAPL § 711"


def test_normalize_statute_source_id_uses_internal_law_id_not_citation_abbrev() -> None:
    normalized = normalize_statute(_load_fixture())
    assert normalized["source_id"] == "RPA/711"


def test_normalize_statute_sets_fixed_source_and_doc_type() -> None:
    normalized = normalize_statute(_load_fixture())
    assert normalized["source"] == "ny_open_legislation"
    assert normalized["doc_type"] == "statute"
    assert normalized["jurisdiction"] == "NY"


def test_normalize_statute_parses_active_date() -> None:
    normalized = normalize_statute(_load_fixture())
    assert normalized["effective_date"] == date(2024, 12, 13)


def test_normalize_statute_preserves_raw_snapshot_verbatim() -> None:
    raw = _load_fixture()
    normalized = normalize_statute(raw)
    assert normalized["raw_snapshot"] == raw


def test_normalize_statute_missing_active_date_does_not_raise() -> None:
    raw = _load_fixture()
    del raw["activeDate"]
    normalized = normalize_statute(raw)
    assert normalized["effective_date"] is None

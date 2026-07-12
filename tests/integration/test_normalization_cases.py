import json
from datetime import date
from pathlib import Path

from pipelines.normalization.cases import normalize_case

FIXTURE = Path(__file__).parent.parent / "fixtures" / "park_west_raw.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_normalize_case_sets_fixed_source_and_doc_type() -> None:
    normalized = normalize_case(_load_fixture())
    assert normalized["source"] == "courtlistener_seed"
    assert normalized["doc_type"] == "case"
    assert normalized["jurisdiction"] == "NY"


def test_normalize_case_citation_and_title_come_from_seed_fields() -> None:
    normalized = normalize_case(_load_fixture())
    assert normalized["citation"] == "47 N.Y.2d 316"
    assert normalized["title"] == "Park West Management Corp. v. Mitchell"
    assert normalized["court"] == "New York Court of Appeals"


def test_normalize_case_source_id_uses_courtlistener_cluster_id() -> None:
    normalized = normalize_case(_load_fixture())
    assert normalized["source_id"] == "5683523"


def test_normalize_case_parses_decision_date() -> None:
    normalized = normalize_case(_load_fixture())
    assert normalized["decision_date"] == date(1979, 6, 7)


def test_normalize_case_effective_date_is_always_none() -> None:
    normalized = normalize_case(_load_fixture())
    assert normalized["effective_date"] is None


def test_normalize_case_preserves_raw_snapshot_verbatim() -> None:
    raw = _load_fixture()
    normalized = normalize_case(raw)
    assert normalized["raw_snapshot"] == raw


def test_normalize_case_missing_decision_date_does_not_raise() -> None:
    raw = _load_fixture()
    del raw["decision_date"]
    normalized = normalize_case(raw)
    assert normalized["decision_date"] is None

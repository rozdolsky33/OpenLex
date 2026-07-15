"""Builds the golden-question evaluation report (site/index.html) from this run's collected
JSON results plus historical run data. See docs/decisions/0004-golden-question-report-and-pages.md.

Usage: uv run python scripts/eval/generate_eval_report.py
Reads (all optional except at least one of results-haiku.json/results-sonnet.json should
exist for a meaningful report; missing inputs render as an explicit "unavailable" state rather
than failing):
    results-haiku.json, results-sonnet.json  -- from tests/evaluation/conftest.py
    freshness-results.json                   -- from scripts/eval/check_statute_freshness.py
    history.ndjson                           -- prior runs' summaries, absent on the first run
Writes: site/index.html, site/history.ndjson
"""

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_SCRIPT_DIR = Path(__file__).parent
_TEMPLATE_DIR = _SCRIPT_DIR / "templates"
_SITE_DIR = Path("site")

HAIKU_RESULTS_PATH = Path("results-haiku.json")
SONNET_RESULTS_PATH = Path("results-sonnet.json")
FRESHNESS_RESULTS_PATH = Path("freshness-results.json")
HISTORY_PATH = Path("history.ndjson")

MAX_HISTORY_RUNS = 20


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _index_results(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    return {r["case_id"]: r for r in payload["results"]}


def _diverges(haiku: dict[str, Any] | None, sonnet: dict[str, Any] | None) -> bool:
    """Flags divergence when the abstain flag differs, or the two models' citation sets are
    fully disjoint. Deliberately NOT flagged on answer-text differences alone -- Haiku and
    Sonnet phrase things at least slightly differently even when citing identically, so
    text-diff-as-divergence would flag nearly every question (see ADR-0004)."""
    if haiku is None or sonnet is None:
        return False
    if haiku.get("actual_abstained") != sonnet.get("actual_abstained"):
        return True
    haiku_citations = set(haiku.get("actual_citations") or [])
    sonnet_citations = set(sonnet.get("actual_citations") or [])
    if not haiku_citations and not sonnet_citations:
        return False
    return not (haiku_citations & sonnet_citations)


def build_report_context() -> dict[str, Any]:
    haiku_payload = _load_json(HAIKU_RESULTS_PATH)
    sonnet_payload = _load_json(SONNET_RESULTS_PATH)
    freshness_payload = _load_json(FRESHNESS_RESULTS_PATH)
    history = _load_history(HISTORY_PATH)

    haiku_by_id = _index_results(haiku_payload)
    sonnet_by_id = _index_results(sonnet_payload)
    all_case_ids = list(dict.fromkeys([*haiku_by_id.keys(), *sonnet_by_id.keys()]))

    rows = []
    for case_id in all_case_ids:
        haiku_result = haiku_by_id.get(case_id)
        sonnet_result = sonnet_by_id.get(case_id)
        source = haiku_result or sonnet_result or {}
        rows.append(
            {
                "case_id": case_id,
                "question": source.get("question", ""),
                "expected_citations": source.get("expected_citations", []),
                "expect_abstain": source.get("expect_abstain", False),
                "haiku": haiku_result,
                "sonnet": sonnet_result,
                "diverges": _diverges(haiku_result, sonnet_result),
            }
        )

    return {
        "haiku_metadata": haiku_payload["run_metadata"] if haiku_payload else None,
        "sonnet_metadata": sonnet_payload["run_metadata"] if sonnet_payload else None,
        "rows": rows,
        "divergence_count": sum(1 for r in rows if r["diverges"]),
        "freshness": freshness_payload,
        "history": history[-MAX_HISTORY_RUNS:],
    }


def render(context: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=select_autoescape(["html"])
    )
    template = env.get_template("eval_report.html.jinja")
    return template.render(**context)


def main() -> None:
    context = build_report_context()
    html = render(context)

    _SITE_DIR.mkdir(exist_ok=True)
    (_SITE_DIR / "index.html").write_text(html)
    if HISTORY_PATH.exists():
        (_SITE_DIR / "history.ndjson").write_text(HISTORY_PATH.read_text())


if __name__ == "__main__":
    main()

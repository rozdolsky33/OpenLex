"""Structured per-question result capture for the golden-question suite -- feeds
scripts/eval/generate_eval_report.py. See docs/decisions/0004-golden-question-report-and-pages.md.

Writes one JSON file (EVAL_RESULTS_PATH, default eval-results.json) at the end of the test
session: {"run_metadata": {...}, "results": [...]}. Tests populate the `eval_result` fixture's
dict with actual response data as soon as they receive it, BEFORE any assertions run, via
pytest's Stash API -- so a failing test still records what it actually got, not just that it
failed (see test_golden_questions.py's use of the `eval_result` fixture).
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

RESULT_KEY = pytest.StashKey[dict[str, Any]]()

_collected_results: list[dict[str, Any]] = []


@pytest.fixture
def eval_result(request: pytest.FixtureRequest) -> dict[str, Any]:
    """A plain dict the test populates with actual response data. Stashed on the test item
    (not just returned) so pytest_runtest_makereport can read it below even when the test
    fails partway through -- whatever was written before the failure is still captured."""
    data: dict[str, Any] = {}
    request.node.stash[RESULT_KEY] = data
    return data


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return

    stashed = item.stash.get(RESULT_KEY, {})
    _collected_results.append(
        {
            **stashed,
            "outcome": report.outcome,
            "duration_seconds": round(report.duration, 3),
            "failure_reason": str(report.longrepr) if report.outcome == "failed" else None,
        }
    )


def pytest_sessionfinish(session: pytest.Session) -> None:
    if not _collected_results:
        return

    results_path = Path(os.environ.get("EVAL_RESULTS_PATH", "eval-results.json"))
    run_id = os.environ.get("GITHUB_RUN_ID")
    workflow_url = (
        f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}"
        if run_id and "GITHUB_SERVER_URL" in os.environ and "GITHUB_REPOSITORY" in os.environ
        else None
    )
    payload = {
        "run_metadata": {
            "model": os.environ.get("ANTHROPIC_MODEL", "unknown"),
            "git_sha": os.environ.get("GITHUB_SHA", "local"),
            "run_id": run_id or "local",
            "workflow_url": workflow_url,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "trigger": os.environ.get("GITHUB_EVENT_NAME", "local"),
        },
        "results": _collected_results,
    }
    results_path.write_text(json.dumps(payload, indent=2))

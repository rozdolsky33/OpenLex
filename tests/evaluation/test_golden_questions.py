"""Golden-question legal-accuracy evaluation harness (see golden_questions.yaml).

Hits a live, already-running API to check the retrieval+generation pipeline's real end-to-end
behavior -- not just code correctness -- against a fixed set of landlord-tenant questions.
Marked `evaluation` and excluded from the default `uv run pytest` run (see the root
pyproject.toml's addopts): it costs real Anthropic API calls and requires a running server.
Run via `scripts/evaluate.sh` instead.
"""

import os
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from openlex_shared.config import settings

pytestmark = pytest.mark.evaluation

API_BASE_URL = os.environ.get("EVAL_API_BASE_URL", "http://localhost:8000")
GOLDEN_QUESTIONS_PATH = Path(__file__).parent / "golden_questions.yaml"
REQUEST_TIMEOUT_SECONDS = 60.0


def _load_golden_questions() -> list[dict[str, Any]]:
    return yaml.safe_load(GOLDEN_QUESTIONS_PATH.read_text())["questions"]


@pytest.fixture(scope="session", autouse=True)
def _require_live_api() -> None:
    try:
        response = httpx.get(f"{API_BASE_URL}/healthz", timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.fail(
            f"API not reachable at {API_BASE_URL}/healthz -- start it first "
            f"(docker compose up -d db api) or set EVAL_API_BASE_URL. ({exc})"
        )


@pytest.fixture(scope="session")
def _auth_token(_require_live_api: None) -> str:
    """POST /query requires a bearer token (see apps/api/src/openlex_api/auth.py).
    POST /auth/register is disabled for this demo (see routers/auth.py) -- only the three
    seeded tier users can log in (apps/api/src/openlex_api/seed_demo_users.py /
    scripts/seed-demo-users.sh must have already been run against the target API). Logs in as
    the seeded Platinum user: the golden-question set (21 cases as of this writing) plus room
    for repeat local runs within the same 4h window needs the highest per-tier quota, not
    Silver/Gold's much tighter limits (see apps/api/src/openlex_api/quota.py)."""
    email = settings.demo_platinum_email
    password = settings.demo_platinum_password
    if not email or not password:
        pytest.fail(
            "DEMO_PLATINUM_EMAIL/DEMO_PLATINUM_PASSWORD aren't set -- seed the demo users "
            "(scripts/seed-demo-users.sh) and ensure .env has them before running the eval "
            "harness."
        )

    login_response = httpx.post(
        f"{API_BASE_URL}/auth/login",
        data={"username": email, "password": password},
        timeout=10.0,
    )
    login_response.raise_for_status()
    return str(login_response.json()["access_token"])


@pytest.mark.parametrize("case", _load_golden_questions(), ids=lambda case: case["id"])
def test_golden_question(
    case: dict[str, Any], _auth_token: str, eval_result: dict[str, Any]
) -> None:
    # Record request-side fields before the call, and actual-response fields as soon as they're
    # received -- BEFORE any assertion below can raise -- so a failing test still reports what
    # it actually got, not just that it failed (see conftest.py's module docstring).
    eval_result["case_id"] = case["id"]
    eval_result["question"] = case["question"]
    eval_result["expected_citations"] = case.get("expected_citations", [])
    eval_result["expect_abstain"] = case.get("expect_abstain", False)

    response = httpx.post(
        f"{API_BASE_URL}/query",
        json={"question": case["question"]},
        headers={"Authorization": f"Bearer {_auth_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()

    eval_result["actual_abstained"] = body["abstained"]
    eval_result["actual_citations"] = [c["citation"] for c in body["citations"]]
    eval_result["actual_answer"] = body["answer"]

    if case.get("expect_abstain", False):
        assert body["abstained"] is True, f"expected abstain, got answer: {body['answer']!r}"
        assert body["citations"] == []
        return

    assert body["abstained"] is False, f"unexpectedly abstained: {body['answer']!r}"
    assert body["answer"].strip(), "answer was empty"
    assert body["disclaimer"], "disclaimer missing"

    got_citations = {c["citation"] for c in body["citations"]}
    expected_citations = set(case["expected_citations"])
    assert got_citations & expected_citations, (
        f"expected one of {expected_citations}, got {got_citations}"
    )

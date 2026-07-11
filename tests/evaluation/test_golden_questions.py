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
    """POST /query requires a bearer token (see apps/api/src/openlex_api/auth.py). Registers
    a fixed eval user, tolerating 409 (already registered) so repeat runs against a
    not-yet-recycled DB don't fail, then logs in for a token."""
    email = "golden-questions-eval@example.com"
    password = "eval-harness-not-a-real-password"

    register_response = httpx.post(
        f"{API_BASE_URL}/auth/register",
        json={"email": email, "password": password},
        timeout=10.0,
    )
    if register_response.status_code not in (201, 409):
        register_response.raise_for_status()

    login_response = httpx.post(
        f"{API_BASE_URL}/auth/login",
        data={"username": email, "password": password},
        timeout=10.0,
    )
    login_response.raise_for_status()
    return str(login_response.json()["access_token"])


@pytest.mark.parametrize("case", _load_golden_questions(), ids=lambda case: case["id"])
def test_golden_question(case: dict[str, Any], _auth_token: str) -> None:
    response = httpx.post(
        f"{API_BASE_URL}/query",
        json={"question": case["question"]},
        headers={"Authorization": f"Bearer {_auth_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()

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

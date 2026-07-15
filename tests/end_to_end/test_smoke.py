# tests/end_to_end/test_smoke.py
"""Full-stack smoke test: proves the golden path (login -> query -> cited answer) is alive
against a live, already-running stack. Deliberately does NOT re-test citation accuracy -- that
is tests/evaluation's job. Marked `e2e` and excluded from the default `uv run pytest` run (see
the root pyproject.toml's addopts): it needs a running server. Run via:

    docker compose up -d --build db api worker
    scripts/compose/ingest.sh statutes
    scripts/seed/seed-demo-users.sh
    uv run pytest tests/end_to_end -v -m e2e
"""

import os

import httpx
import pytest
from openlex_shared.config import settings

pytestmark = pytest.mark.e2e

API_BASE_URL = os.environ.get("EVAL_API_BASE_URL", "http://localhost:8000")
REQUEST_TIMEOUT_SECONDS = 60.0


def test_smoke_login_query_cited_answer() -> None:
    email = settings.demo_platinum_email
    password = settings.demo_platinum_password
    assert email and password, (
        "DEMO_PLATINUM_EMAIL/DEMO_PLATINUM_PASSWORD aren't set -- seed the demo users "
        "(scripts/seed/seed-demo-users.sh) and ensure .env has them before running this test."
    )

    login_response = httpx.post(
        f"{API_BASE_URL}/auth/login",
        data={"username": email, "password": password},
        timeout=10.0,
    )
    login_response.raise_for_status()
    token = login_response.json()["access_token"]

    question = (
        "How is a landlord-tenant summary proceeding commenced, and what notice of petition "
        "must be given?"
    )
    query_response = httpx.post(
        f"{API_BASE_URL}/query",
        json={"question": question},
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    query_response.raise_for_status()
    body = query_response.json()

    assert body["abstained"] is False, f"unexpectedly abstained: {body['answer']!r}"
    assert body["answer"].strip(), "answer was empty"
    assert len(body["citations"]) >= 1, "expected at least one citation"
    assert body["disclaimer"], "disclaimer missing"

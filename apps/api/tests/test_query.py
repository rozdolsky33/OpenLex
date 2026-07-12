"""Tests for POST /query (apps/api/src/openlex_api/routers/query.py).

handle_query_turn (legal_generation.conversation) is patched at the router module's import
site so these tests exercise only routing/validation/error-mapping -- no real DB, embedding
model, reformulation, or Claude call. See
packages/legal_generation/tests/test_conversation.py for orchestration-level tests of
handle_query_turn itself.

check_and_consume_quota (openlex_api.quota) is likewise patched by default (via
_mock_quota's autouse fixture) to a fixed UserStatus so routing tests aren't exercising real
quota SQL against a mocked session -- see test_quota.py for quota-logic coverage and the
dedicated tests below for the 429/usage-attachment behavior this router adds.

The auth dependency is overridden with a fake user so these tests don't need a real JWT --
see test_auth.py for auth-specific coverage, and test_query_requires_authentication below for
the one case that deliberately leaves auth un-overridden.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from legal_generation.conversation import ConversationNotFound
from legal_models.orm import User
from legal_models.schemas import Citation, QueryResponse, UserStatus
from openlex_api.auth import get_current_user
from openlex_api.main import app
from openlex_api.quota import QuotaExceeded
from openlex_shared.db import get_session

QUOTA_RESET_AT = datetime.now(UTC) + timedelta(hours=4)

client = TestClient(app)

FAKE_USER = User(
    id=uuid.uuid4(),
    email="tenant@example.com",
    password_hash="unused",
    created_at=datetime.now(),
    tier="gold",
    request_count=1,
    period_started_at=datetime.now(UTC),
)

FAKE_USAGE = UserStatus(
    email=FAKE_USER.email,
    tier="gold",
    request_count=1,
    request_limit=50,
    period_reset_at=QUOTA_RESET_AT,
)


@pytest.fixture(autouse=True)
def _mock_db_session():
    async def _get_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _mock_quota():
    with patch(
        "openlex_api.routers.query.check_and_consume_quota",
        AsyncMock(return_value=FAKE_USAGE),
    ) as mocked:
        yield mocked


def test_query_returns_the_generated_answer_verbatim() -> None:
    expected = QueryResponse(
        answer="A tenant is defined as...",
        citations=[
            Citation(citation="RPAPL § 711", doc_type="statute", snippet="A tenant shall...")
        ],
        abstained=False,
        conversation_id="11111111-1111-1111-1111-111111111111",
    )
    with patch("openlex_api.routers.query.handle_query_turn", AsyncMock(return_value=expected)):
        response = client.post("/query", json={"question": "what is a tenant?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == expected.answer
    assert body["abstained"] is False
    assert body["citations"][0]["citation"] == "RPAPL § 711"
    assert body["disclaimer"] == expected.disclaimer
    assert body["conversation_id"] == expected.conversation_id


def test_query_passes_question_conversation_id_top_k_and_doc_type_through() -> None:
    mock_handle = AsyncMock(
        return_value=QueryResponse(answer="", citations=[], abstained=True, conversation_id="abc")
    )
    with patch("openlex_api.routers.query.handle_query_turn", mock_handle):
        response = client.post(
            "/query",
            json={
                "question": "how much notice?",
                "top_k": 3,
                "doc_type": "statute",
                "conversation_id": "abc",
            },
        )

    assert response.status_code == 200
    mock_handle.assert_awaited_once()
    call_args, call_kwargs = mock_handle.call_args
    assert call_args[1] == "how much notice?"
    assert call_kwargs == {
        "conversation_id": "abc",
        "top_k": 3,
        "doc_type": "statute",
        "user_id": FAKE_USER.id,
    }


def test_query_returns_404_when_conversation_id_is_unknown() -> None:
    with patch(
        "openlex_api.routers.query.handle_query_turn",
        AsyncMock(side_effect=ConversationNotFound("conversation abc not found")),
    ):
        response = client.post(
            "/query", json={"question": "what about pets?", "conversation_id": "abc"}
        )

    assert response.status_code == 404


def test_query_rejects_missing_question() -> None:
    response = client.post("/query", json={})
    assert response.status_code == 422


def test_query_rejects_invalid_doc_type() -> None:
    response = client.post(
        "/query", json={"question": "what is a tenant?", "doc_type": "not-a-real-type"}
    )
    assert response.status_code == 422


def test_query_requires_authentication() -> None:
    del app.dependency_overrides[get_current_user]
    response = client.post("/query", json={"question": "what is a tenant?"})
    assert response.status_code == 401


def test_query_attaches_usage_to_a_successful_response() -> None:
    expected = QueryResponse(answer="ok", citations=[], abstained=False, conversation_id="abc")
    with patch("openlex_api.routers.query.handle_query_turn", AsyncMock(return_value=expected)):
        response = client.post("/query", json={"question": "what is a tenant?"})

    assert response.status_code == 200
    usage = response.json()["usage"]
    assert usage["tier"] == "gold"
    assert usage["request_count"] == 1
    assert usage["request_limit"] == 50


def test_query_returns_429_when_quota_exceeded(_mock_quota: AsyncMock) -> None:
    reset_at = datetime.now(UTC) + timedelta(hours=2)
    _mock_quota.side_effect = QuotaExceeded(tier="silver", limit=15, reset_at=reset_at)

    response = client.post("/query", json={"question": "what is a tenant?"})

    assert response.status_code == 429
    body = response.json()["detail"]
    assert body["error"] == "quota_exceeded"
    assert body["tier"] == "silver"
    assert body["limit"] == 15
    assert body["reset_at"] == reset_at.isoformat()

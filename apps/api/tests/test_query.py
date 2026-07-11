"""Tests for POST /query (apps/api/src/openlex_api/routers/query.py).

handle_query_turn (legal_generation.conversation) is patched at the router module's import
site so these tests exercise only routing/validation/error-mapping -- no real DB, embedding
model, reformulation, or Claude call. See
packages/legal_generation/tests/test_conversation.py for orchestration-level tests of
handle_query_turn itself.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from legal_generation.conversation import ConversationNotFound
from legal_models.schemas import Citation, QueryResponse
from openlex_api.main import app
from openlex_shared.db import get_session

client = TestClient(app)


@pytest.fixture(autouse=True)
def _mock_db_session():
    async def _get_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _get_session
    yield
    app.dependency_overrides.clear()


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
    assert call_kwargs == {"conversation_id": "abc", "top_k": 3, "doc_type": "statute"}


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

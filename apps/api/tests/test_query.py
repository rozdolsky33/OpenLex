"""Tests for POST /query (apps/api/src/openlex_api/routers/query.py).

hybrid_search and generate_answer are patched at the router module's import site so these
tests exercise only routing/validation/wiring -- no real DB, embedding model, or Claude call.
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from legal_models.schemas import Citation, QueryResponse
from legal_retrieval.search import SearchResult
from openlex_api.main import app
from openlex_shared.db import get_session

client = TestClient(app)

PASSAGE = SearchResult(
    chunk_id="chunk-1",
    document_id="doc-1",
    text="A tenant shall include an occupant...",
    citation="RPAPL § 711",
    doc_type="statute",
    title="Grounds where landlord-tenant relationship exists",
    court=None,
    effective_date=date(2024, 12, 13),
    url="https://legislation.nysenate.gov/api/3/laws/RPA/711",
    score=0.9,
)


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
    )
    with (
        patch("openlex_api.routers.query.hybrid_search", AsyncMock(return_value=[PASSAGE])),
        patch("openlex_api.routers.query.generate_answer", AsyncMock(return_value=expected)),
    ):
        response = client.post("/query", json={"question": "what is a tenant?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == expected.answer
    assert body["abstained"] is False
    assert body["citations"][0]["citation"] == "RPAPL § 711"
    assert body["disclaimer"] == expected.disclaimer


def test_query_passes_question_top_k_and_doc_type_through_to_search() -> None:
    mock_search = AsyncMock(return_value=[])
    mock_generate = AsyncMock(return_value=QueryResponse(answer="", citations=[], abstained=True))
    with (
        patch("openlex_api.routers.query.hybrid_search", mock_search),
        patch("openlex_api.routers.query.generate_answer", mock_generate),
    ):
        response = client.post(
            "/query",
            json={"question": "how much notice?", "top_k": 3, "doc_type": "statute"},
        )

    assert response.status_code == 200
    mock_search.assert_awaited_once()
    call_args, call_kwargs = mock_search.call_args
    assert call_args[1] == "how much notice?"
    assert call_kwargs == {"top_k": 3, "doc_type": "statute"}


def test_query_passes_search_results_and_question_through_to_generation() -> None:
    mock_generate = AsyncMock(
        return_value=QueryResponse(answer="ok", citations=[], abstained=False)
    )
    with (
        patch("openlex_api.routers.query.hybrid_search", AsyncMock(return_value=[PASSAGE])),
        patch("openlex_api.routers.query.generate_answer", mock_generate),
    ):
        client.post("/query", json={"question": "what is a tenant?"})

    mock_generate.assert_awaited_once_with("what is a tenant?", [PASSAGE])


def test_query_rejects_missing_question() -> None:
    response = client.post("/query", json={})
    assert response.status_code == 422


def test_query_rejects_invalid_doc_type() -> None:
    response = client.post(
        "/query", json={"question": "what is a tenant?", "doc_type": "not-a-real-type"}
    )
    assert response.status_code == 422

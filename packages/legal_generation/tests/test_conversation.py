"""Unit tests for handle_query_turn's orchestration -- see ADR-0003.

reformulate_query, hybrid_search, and generate_answer are patched at this module's import site
so these tests exercise only the load/reformulate/search/generate/persist wiring, not any real
Postgres connection or Claude call. See tests/integration/test_conversations.py for the
ORM/persistence layer itself, and packages/legal_generation/tests/test_reformulate.py /
test_generator.py for those functions' own behavior.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from legal_generation.conversation import handle_query_turn
from legal_generation.types import ConversationTurn
from legal_models.orm import Conversation, Message
from legal_models.schemas import Citation, QueryResponse
from legal_retrieval.search import SearchResult
from sqlalchemy.ext.asyncio import AsyncSession

PASSAGE = SearchResult(
    chunk_id="chunk-1",
    document_id="doc-1",
    text="A tenant shall include an occupant...",
    citation="RPAPL § 711",
    doc_type="statute",
    title="Grounds where landlord-tenant relationship exists",
    court=None,
    effective_date=None,
    url="https://legislation.nysenate.gov/api/3/laws/RPA/711",
    score=0.9,
)


def _mock_session_that_assigns_id_on_flush() -> AsyncMock:
    """A real `session.flush()` assigns Python-side-default ids (like Conversation.id's
    `default=uuid.uuid4`) to newly added, not-yet-flushed rows. Simulate exactly that so
    _load_conversation's new-conversation branch behaves like it would against a real DB.

    spec=AsyncSession matters here: without it, a bare AsyncMock() treats every attribute
    (including sync methods like .add()) as async, so a synchronous session.add(x) call
    returns an un-awaited coroutine and pytest emits a RuntimeWarning for it."""
    session = AsyncMock(spec=AsyncSession)
    added: list = []
    session.add.side_effect = added.append

    async def _flush() -> None:
        for obj in added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    session.flush.side_effect = _flush
    return session


async def test_handle_query_turn_creates_a_new_conversation_when_none_given() -> None:
    session = _mock_session_that_assigns_id_on_flush()
    generated = QueryResponse(answer="A tenant is defined as...", citations=[], abstained=False)

    with (
        patch(
            "legal_generation.conversation.reformulate_query",
            AsyncMock(side_effect=lambda history, question: question),
        ),
        patch("legal_generation.conversation.hybrid_search", AsyncMock(return_value=[PASSAGE])),
        patch("legal_generation.conversation.generate_answer", AsyncMock(return_value=generated)),
    ):
        response = await handle_query_turn(session, "what is a tenant?")

    assert response.conversation_id is not None
    assert response.answer == "A tenant is defined as..."
    session.commit.assert_awaited_once()


async def test_handle_query_turn_loads_history_for_an_existing_conversation() -> None:
    conversation_id = uuid.uuid4()
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = Conversation(id=conversation_id)

    prior_message = Message(
        conversation_id=conversation_id,
        turn_index=0,
        question="what is a tenant?",
        standalone_question=None,
        answer="A tenant is defined as...",
        citations=[],
        abstained=False,
    )
    scalars_result = MagicMock()
    scalars_result.all.return_value = [prior_message]
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result
    session.execute.return_value = execute_result

    generated = QueryResponse(answer="Yes, pets are allowed...", citations=[], abstained=False)
    mock_reformulate = AsyncMock(return_value="does the lease allow pets?")

    with (
        patch("legal_generation.conversation.reformulate_query", mock_reformulate),
        patch("legal_generation.conversation.hybrid_search", AsyncMock(return_value=[PASSAGE])),
        patch(
            "legal_generation.conversation.generate_answer", AsyncMock(return_value=generated)
        ) as mock_generate,
    ):
        response = await handle_query_turn(
            session, "what about pets?", conversation_id=str(conversation_id)
        )

    assert response.conversation_id == str(conversation_id)
    mock_reformulate.assert_awaited_once()
    history_arg = mock_reformulate.call_args.args[0]
    assert history_arg == [
        ConversationTurn(question="what is a tenant?", answer="A tenant is defined as...")
    ]
    mock_generate.assert_awaited_once()
    assert mock_generate.call_args.kwargs["history"] == history_arg


async def test_handle_query_turn_raises_value_error_for_unknown_conversation_id() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = None

    with pytest.raises(ValueError):
        await handle_query_turn(session, "what about pets?", conversation_id=str(uuid.uuid4()))


async def test_handle_query_turn_persists_the_new_turn_and_commits() -> None:
    session = _mock_session_that_assigns_id_on_flush()
    generated = QueryResponse(
        answer="A tenant is defined as...",
        citations=[Citation(citation="RPAPL § 711", doc_type="statute", snippet="A tenant...")],
        abstained=False,
    )

    with (
        patch(
            "legal_generation.conversation.reformulate_query",
            AsyncMock(side_effect=lambda history, question: question),
        ),
        patch("legal_generation.conversation.hybrid_search", AsyncMock(return_value=[PASSAGE])),
        patch("legal_generation.conversation.generate_answer", AsyncMock(return_value=generated)),
    ):
        await handle_query_turn(session, "what is a tenant?")

    persisted = session.add.call_args_list[-1].args[0]
    assert isinstance(persisted, Message)
    assert persisted.question == "what is a tenant?"
    assert persisted.turn_index == 0
    assert persisted.standalone_question is None
    assert persisted.citations == [
        {
            "citation": "RPAPL § 711",
            "doc_type": "statute",
            "title": None,
            "court": None,
            "date": None,
            "url": None,
            "snippet": "A tenant...",
        }
    ]
    session.commit.assert_awaited_once()

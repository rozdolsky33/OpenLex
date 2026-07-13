"""Per-turn conversation orchestration for POST /query -- see ADR-0003.

Ties together conversation load/create, query reformulation, retrieval, grounded generation,
and turn persistence into the one function apps/api/routers/query.py calls, so that router
stays a thin call-through with no domain logic of its own.
"""

import uuid

from legal_models.orm import Conversation, Message
from legal_models.schemas import QueryResponse
from legal_retrieval.search import SearchResult, hybrid_search
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_generation.generator import generate_answer
from legal_generation.reformulate import reformulate_query
from legal_generation.types import ConversationTurn

QUERY_ABSTAINED_TOTAL = Counter(
    "openlex_query_abstained_total",
    "Turns where generate_answer abstained (hard abstain on empty retrieval, or the "
    "grounded-answer-contract's defense-in-depth abstain) -- see the Product & Usage "
    "dashboard's abstain-rate panel, which divides this by openlex_http_requests_total"
    '{route="/query"}.',
)


class ConversationNotFound(Exception):
    """Raised when a given conversation_id doesn't exist, or isn't a valid UUID at all --
    both map to the same client-facing 404 in apps/api/routers/query.py."""


async def _load_conversation(
    session: AsyncSession, conversation_id: str | None, user_id: uuid.UUID
) -> tuple[Conversation, list[ConversationTurn]]:
    if conversation_id is None:
        conversation = Conversation(user_id=user_id)
        session.add(conversation)
        await session.flush()  # assigns conversation.id, needed for the Message FK below
        return conversation, []

    try:
        conversation_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise ConversationNotFound(f"conversation {conversation_id} not found") from exc

    # Scoped by owner, not session.get (which can't filter) -- a wrong-owner conversation_id
    # raises ConversationNotFound identically to a nonexistent one, so callers can't probe for
    # another user's conversation ids (see Phase 2 of the GA-readiness roadmap).
    found_conversation = (
        (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_uuid, Conversation.user_id == user_id
                )
            )
        )
        .scalars()
        .first()
    )
    if found_conversation is None:
        raise ConversationNotFound(f"conversation {conversation_id} not found")
    conversation = found_conversation

    rows = (
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.turn_index)
            )
        )
        .scalars()
        .all()
    )
    history = [ConversationTurn(question=m.question, answer=m.answer) for m in rows]
    return conversation, history


async def handle_query_turn(
    session: AsyncSession,
    question: str,
    user_id: uuid.UUID,
    conversation_id: str | None = None,
    top_k: int = 8,
    doc_type: str | None = None,
) -> QueryResponse:
    conversation, history = await _load_conversation(session, conversation_id, user_id)

    standalone_question = await reformulate_query(history, question)
    passages: list[SearchResult] = await hybrid_search(
        session, standalone_question, top_k=top_k, doc_type=doc_type
    )
    response = await generate_answer(question, passages, history=history)
    if response.abstained:
        QUERY_ABSTAINED_TOTAL.inc()

    session.add(
        Message(
            conversation_id=conversation.id,
            turn_index=len(history),
            question=question,
            # Only store a distinct standalone_question when reformulation actually ran (turn
            # 0's reformulate_query always returns the raw question unchanged -- storing it
            # again as "standalone_question" would be redundant, see ADR-0003 §2's schema note).
            standalone_question=standalone_question if history else None,
            answer=response.answer,
            citations=[c.model_dump() for c in response.citations],
            abstained=response.abstained,
        )
    )
    await session.commit()

    return response.model_copy(update={"conversation_id": str(conversation.id)})

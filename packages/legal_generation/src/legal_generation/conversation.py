"""Per-turn conversation orchestration for POST /query -- see ADR-0003.

Ties together conversation load/create, query reformulation, retrieval, grounded generation,
and turn persistence into the one function apps/api/routers/query.py calls, so that router
stays a thin call-through with no domain logic of its own.
"""

import uuid

from legal_models.orm import Conversation, Message
from legal_models.schemas import QueryResponse
from legal_retrieval.search import SearchResult, hybrid_search
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_generation.generator import generate_answer
from legal_generation.reformulate import reformulate_query
from legal_generation.types import ConversationTurn


async def _load_conversation(
    session: AsyncSession, conversation_id: str | None
) -> tuple[Conversation, list[ConversationTurn]]:
    if conversation_id is None:
        conversation = Conversation()
        session.add(conversation)
        await session.flush()  # assigns conversation.id, needed for the Message FK below
        return conversation, []

    found_conversation = await session.get(Conversation, uuid.UUID(conversation_id))
    if found_conversation is None:
        raise ValueError(f"conversation {conversation_id} not found")
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
    conversation_id: str | None = None,
    top_k: int = 8,
    doc_type: str | None = None,
) -> QueryResponse:
    conversation, history = await _load_conversation(session, conversation_id)

    standalone_question = await reformulate_query(history, question)
    passages: list[SearchResult] = await hybrid_search(
        session, standalone_question, top_k=top_k, doc_type=doc_type
    )
    response = await generate_answer(question, passages, history=history)

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

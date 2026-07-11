"""Integration tests for the Conversation/Message persistence layer (packages/legal_models/
src/legal_models/orm.py) added by ADR-0003 -- hits a real Postgres, see
tests/integration/README.md for how to run these."""

import uuid

from legal_models.orm import Conversation, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


async def test_creating_a_conversation_assigns_a_uuid(db_session) -> None:
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()

    assert conversation.id is not None
    assert isinstance(conversation.id, uuid.UUID)


async def test_messages_persist_and_load_ordered_by_turn_index(db_session) -> None:
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()

    db_session.add(
        Message(
            conversation_id=conversation.id,
            turn_index=1,
            question="what about pets?",
            standalone_question="does the lease allow pets?",
            answer="Yes, subject to...",
            citations=[{"citation": "RPL § 235-B", "doc_type": "statute", "snippet": "..."}],
            abstained=False,
        )
    )
    db_session.add(
        Message(
            conversation_id=conversation.id,
            turn_index=0,
            question="what is a tenant?",
            standalone_question=None,
            answer="A tenant is defined as...",
            citations=[],
            abstained=False,
        )
    )
    await db_session.flush()

    rows = (
        (
            await db_session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.turn_index)
            )
        )
        .scalars()
        .all()
    )

    assert [m.turn_index for m in rows] == [0, 1]
    assert rows[0].standalone_question is None
    assert rows[1].citations == [
        {"citation": "RPL § 235-B", "doc_type": "statute", "snippet": "..."}
    ]


async def test_duplicate_turn_index_in_same_conversation_is_rejected(db_session) -> None:
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()

    db_session.add(
        Message(
            conversation_id=conversation.id,
            turn_index=0,
            question="what is a tenant?",
            standalone_question=None,
            answer="A tenant is defined as...",
            citations=[],
            abstained=False,
        )
    )
    await db_session.flush()

    db_session.add(
        Message(
            conversation_id=conversation.id,
            turn_index=0,
            question="a different question reusing turn_index 0",
            standalone_question=None,
            answer="...",
            citations=[],
            abstained=False,
        )
    )

    raised = False
    try:
        await db_session.flush()
    except IntegrityError:
        raised = True
    await db_session.rollback()

    assert raised


async def test_deleting_a_conversation_cascades_to_its_messages(db_session) -> None:
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()

    db_session.add(
        Message(
            conversation_id=conversation.id,
            turn_index=0,
            question="what is a tenant?",
            standalone_question=None,
            answer="A tenant is defined as...",
            citations=[],
            abstained=False,
        )
    )
    await db_session.flush()

    await db_session.delete(conversation)
    await db_session.flush()

    remaining = (
        (
            await db_session.execute(
                select(Message).where(Message.conversation_id == conversation.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []

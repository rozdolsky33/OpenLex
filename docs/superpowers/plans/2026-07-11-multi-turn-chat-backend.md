# Multi-turn Conversational Chat: Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `POST /query` to support server-persisted, multi-turn conversation (create/continue via `conversation_id`, Claude-based follow-up reformulation for retrieval, grounded-answer contract enforced per turn), fully testable via `pytest`/`curl` with no frontend code.

**Architecture:** New `conversations`/`messages` Postgres tables persist turns. A new orchestration function (`legal_generation.conversation.handle_query_turn`) loads history, reformulates follow-ups, runs existing `hybrid_search`, calls an extended `generate_answer` with history, and persists the new turn — called from a thinned-out `POST /query` router. CORS is added so a later `apps/web` (port 5173) can call this API.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async ORM, Postgres/pgvector, Anthropic SDK, pytest/pytest-asyncio.

## Global Constraints

- This plan covers **only the backend** (see ADR-0003's "Consequences": two-phase rollout, backend fully testable before any frontend code exists). The `apps/web` scaffold is a separate, later plan.
- The grounded-answer contract (hard-abstain on empty retrieval, server-rebuilt citations) must hold **per turn** — history never overrides it (ADR-0003 §4).
- Reformulation (ADR-0003 §3) is skipped entirely on turn 0, and **fails open** (falls back to the raw question) if the Claude call errors — it improves retrieval quality, it is not load-bearing for correctness.
- No auth exists yet; `conversation_id` is an accepted bearer-token-style shared secret (ADR-0003 Consequences) — this plan does not add auth.
- New migration file: `migrations/postgres/0002_conversations.sql`, following the existing `documents`/`chunks` UUID + FK + `ON DELETE CASCADE` pattern (see `migrations/postgres/0001_init.sql`).
- All new/changed Python files must pass `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy apps packages` before being considered done.
- Full reference: `docs/decisions/0003-conversational-chat-and-web-ui.md`.

---

### Task 1: Migration for `conversations`/`messages`, and multi-file migration support

**Files:**
- Create: `migrations/postgres/0002_conversations.sql`
- Modify: `docker-compose.yml` (both `db` and `db-test` services' volume mounts)
- Modify: `scripts/seed-local-db.sh`

**Interfaces:**
- Produces: Postgres tables `conversations(id, created_at)` and `messages(id, conversation_id, turn_index, question, standalone_question, answer, citations, abstained, created_at)`, with `UNIQUE (conversation_id, turn_index)` and `ON DELETE CASCADE` from `messages.conversation_id` to `conversations.id`. Every later task in this plan depends on these tables existing.

- [ ] **Step 1: Write the migration file**

Create `migrations/postgres/0002_conversations.sql`:

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id      UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_index           INT NOT NULL,
    question             TEXT NOT NULL,
    standalone_question  TEXT,             -- reformulated query used for retrieval; null on turn 0
    answer               TEXT NOT NULL,
    citations            JSONB NOT NULL,   -- serialized Citation[]
    abstained            BOOLEAN NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages (conversation_id);
```

- [ ] **Step 2: Make both `db` and `db-test` compose services apply every migration file, not just `0001_init.sql`**

In `docker-compose.yml`, the `db` service currently has:

```yaml
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./migrations/postgres/0001_init.sql:/docker-entrypoint-initdb.d/0001_init.sql
```

Change the second line to mount the whole directory (Postgres's entrypoint runs every `*.sql`/`*.sh` file in `/docker-entrypoint-initdb.d` in sorted order on first init, so numbered migration files just need to exist there):

```yaml
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./migrations/postgres:/docker-entrypoint-initdb.d
```

The `db-test` service currently has:

```yaml
    volumes:
      - ./migrations/postgres/0001_init.sql:/docker-entrypoint-initdb.d/0001_init.sql
```

Change it the same way:

```yaml
    volumes:
      - ./migrations/postgres:/docker-entrypoint-initdb.d
```

- [ ] **Step 3: Make `scripts/seed-local-db.sh` apply every migration file in order**

Replace the whole file:

```bash
#!/usr/bin/env bash
# Apply the Postgres schema to a fresh local db container (docker-compose's db service
# already does this automatically via docker-entrypoint-initdb.d on first boot — this script
# is for re-applying after a manual `docker compose down -v` / schema change without a
# full volume reset). Applies every migrations/postgres/*.sql file in sorted (numeric prefix)
# order, same as docker-entrypoint-initdb.d does on first boot.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

for migration in migrations/postgres/*.sql; do
  echo "Applying $migration..."
  docker compose exec -T db psql -U openlex -d openlex < "$migration"
done
```

- [ ] **Step 4: Reset the test database and verify both migrations applied**

Run: `scripts/test-db.sh reset`

Then run: `docker compose exec -T db-test psql -U openlex_test -d openlex_test -c '\dt'`

Expected output includes both the pre-existing and new tables:
```
             List of relations
 Schema |     Name      | Type  |    Owner
--------+---------------+-------+-------------
 public | chunks        | table | openlex_test
 public | conversations | table | openlex_test
 public | documents     | table | openlex_test
 public | messages      | table | openlex_test
```

- [ ] **Step 5: Commit**

```bash
git add migrations/postgres/0002_conversations.sql docker-compose.yml scripts/seed-local-db.sh
git commit -m "Add conversations/messages migration; apply all migration files, not just 0001"
```

---

### Task 2: `Conversation`/`Message` ORM models and `conversation_id` schema fields

**Files:**
- Modify: `packages/legal_models/src/legal_models/orm.py`
- Modify: `packages/legal_models/src/legal_models/schemas.py`
- Create: `packages/legal_models/tests/__init__.py` (empty — this package has no `tests/` dir yet)
- Create: `packages/legal_models/tests/test_schemas.py`
- Create: `tests/integration/test_conversations.py`

**Interfaces:**
- Consumes: Task 1's `conversations`/`messages` tables.
- Produces: `legal_models.orm.Conversation` (fields: `id`, `created_at`), `legal_models.orm.Message` (fields: `id`, `conversation_id`, `turn_index`, `question`, `standalone_question`, `answer`, `citations`, `abstained`, `created_at`); `legal_models.schemas.QueryRequest.conversation_id: str | None = None`; `legal_models.schemas.QueryResponse.conversation_id: str | None = None`.

- [ ] **Step 1: Write the failing schema test**

Create `packages/legal_models/tests/__init__.py` (empty file).

Create `packages/legal_models/tests/test_schemas.py`:

```python
from legal_models.schemas import QueryRequest, QueryResponse


def test_query_request_conversation_id_defaults_to_none() -> None:
    req = QueryRequest(question="what is a tenant?")
    assert req.conversation_id is None


def test_query_request_accepts_a_conversation_id() -> None:
    req = QueryRequest(question="what about pets?", conversation_id="abc-123")
    assert req.conversation_id == "abc-123"


def test_query_response_conversation_id_defaults_to_none() -> None:
    resp = QueryResponse(answer="A tenant is...", citations=[], abstained=False)
    assert resp.conversation_id is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --package legal-models pytest packages/legal_models/tests -v`
Expected: FAIL with `TypeError: QueryRequest.__init__() got an unexpected keyword argument 'conversation_id'` (or a pydantic validation error to the same effect) on the second test, and the first/third tests also fail once you try to access `.conversation_id` (`AttributeError`).

- [ ] **Step 3: Add `conversation_id` to `QueryRequest` and `QueryResponse`**

In `packages/legal_models/src/legal_models/schemas.py`, change:

```python
class QueryRequest(BaseModel):
    question: str
    doc_type: Literal["statute", "case"] | None = None
    top_k: int = 8
```

to:

```python
class QueryRequest(BaseModel):
    question: str
    doc_type: Literal["statute", "case"] | None = None
    top_k: int = 8
    conversation_id: str | None = None
```

And change:

```python
class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    abstained: bool
    disclaimer: str = DISCLAIMER
```

to:

```python
class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    abstained: bool
    disclaimer: str = DISCLAIMER
    conversation_id: str | None = None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run --package legal-models pytest packages/legal_models/tests -v`
Expected: `3 passed`

- [ ] **Step 5: Write the failing ORM integration test**

Create `tests/integration/test_conversations.py`:

```python
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
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/integration/test_conversations.py -v`
Expected: FAIL with `ImportError: cannot import name 'Conversation' from 'legal_models.orm'`

- [ ] **Step 7: Add `Conversation` and `Message` to `orm.py`**

In `packages/legal_models/src/legal_models/orm.py`, change the sqlalchemy import line:

```python
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
```

to:

```python
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
```

Then append, after the `Chunk` class:

```python
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    # No `relationship()` back to Conversation (unlike Document/Chunk) -- callers always query
    # messages explicitly (`select(Message).where(...).order_by(...)`) rather than lazy-loading
    # a `.messages` attribute, which would raise under AsyncSession without extra eager-loading
    # setup. Cascade delete is enforced at the DB level (ON DELETE CASCADE in the migration).
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    standalone_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
```

- [ ] **Step 8: Run it to verify it passes**

Run: `uv run pytest tests/integration/test_conversations.py -v`
Expected: `4 passed`

- [ ] **Step 9: Run the full default suite and lint/typecheck**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy apps packages`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add packages/legal_models/src/legal_models/orm.py packages/legal_models/src/legal_models/schemas.py packages/legal_models/tests tests/integration/test_conversations.py
git commit -m "Add Conversation/Message ORM models and conversation_id schema fields"
```

---

### Task 3: `ConversationTurn` type and Claude-based query reformulation

**Files:**
- Create: `packages/legal_generation/src/legal_generation/types.py`
- Create: `packages/legal_generation/src/legal_generation/reformulate.py`
- Create: `packages/legal_generation/tests/test_reformulate.py`

**Interfaces:**
- Produces: `legal_generation.types.ConversationTurn` (dataclass: `question: str`, `answer: str`); `legal_generation.reformulate.reformulate_query(history: list[ConversationTurn], question: str) -> str` (async; returns `question` unchanged if `history` is empty or the Claude call errors).

- [ ] **Step 1: Write the failing test**

Create `packages/legal_generation/tests/test_reformulate.py`:

```python
from unittest.mock import AsyncMock, patch

import anthropic
import httpx
from legal_generation.reformulate import reformulate_query
from legal_generation.types import ConversationTurn


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


async def test_reformulate_query_skips_claude_call_on_first_turn() -> None:
    with patch("legal_generation.reformulate.anthropic.AsyncAnthropic") as mock_anthropic_cls:
        result = await reformulate_query([], "how much notice is required?")

    assert result == "how much notice is required?"
    mock_anthropic_cls.assert_not_called()


async def test_reformulate_query_returns_rewritten_text_from_claude() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = type(
        "Response", (), {"content": [_TextBlock("does the lease's no-pets clause apply here?")]}
    )()
    history = [ConversationTurn(question="what is a tenant?", answer="A tenant is defined as...")]

    with patch("legal_generation.reformulate.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await reformulate_query(history, "what about pets?")

    assert result == "does the lease's no-pets clause apply here?"


async def test_reformulate_query_falls_back_to_raw_question_on_claude_error() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com")
    )
    history = [ConversationTurn(question="what is a tenant?", answer="A tenant is defined as...")]

    with patch("legal_generation.reformulate.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await reformulate_query(history, "what about pets?")

    assert result == "what about pets?"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --package legal-generation pytest packages/legal_generation/tests/test_reformulate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'legal_generation.reformulate'`

- [ ] **Step 3: Write `types.py`**

Create `packages/legal_generation/src/legal_generation/types.py`:

```python
"""Shared conversation types for multi-turn generation -- see ADR-0003."""

from dataclasses import dataclass


@dataclass
class ConversationTurn:
    question: str
    answer: str
```

- [ ] **Step 4: Write `reformulate.py`**

Create `packages/legal_generation/src/legal_generation/reformulate.py`:

```python
"""Follow-up query reformulation for multi-turn retrieval -- see ADR-0003 §3.

Turn 0 (no history) never calls Claude here: a fresh question is already standalone, so
skipping this keeps single-turn latency/cost/behavior (and the golden-question eval suite)
unaffected by multi-turn support existing at all.
"""

import anthropic
from openlex_shared.config import settings

from legal_generation.types import ConversationTurn

_REFORMULATE_PROMPT = """Given the conversation so far and a follow-up question, rewrite the \
follow-up as a standalone question that captures its full meaning without relying on the \
earlier turns. If the follow-up is already standalone, return it unchanged. Respond with ONLY \
the rewritten question, no other text.

Conversation so far:
{history}

Follow-up question: {question}"""


def _format_history(history: list[ConversationTurn]) -> str:
    return "\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in history)


async def reformulate_query(history: list[ConversationTurn], question: str) -> str:
    """Returns `question` unchanged when `history` is empty, or if the Claude call errors --
    fails open since reformulation improves retrieval quality but isn't load-bearing for
    correctness the way the abstain/citation contract is (see ADR-0003 §3)."""
    if not history:
        return question

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    prompt = _REFORMULATE_PROMPT.format(history=_format_history(history), question=question)
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError:
        return question

    text_block = next(block for block in response.content if block.type == "text")
    return text_block.text.strip()
```

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run --package legal-generation pytest packages/legal_generation/tests/test_reformulate.py -v`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add packages/legal_generation/src/legal_generation/types.py packages/legal_generation/src/legal_generation/reformulate.py packages/legal_generation/tests/test_reformulate.py
git commit -m "Add ConversationTurn type and Claude-based follow-up query reformulation"
```

---

### Task 4: `generate_answer` replays conversation history

**Files:**
- Modify: `packages/legal_generation/src/legal_generation/generator.py`
- Modify: `packages/legal_generation/tests/test_generator.py`

**Interfaces:**
- Consumes: Task 3's `legal_generation.types.ConversationTurn`.
- Produces: `legal_generation.generator.generate_answer(question: str, passages: list[SearchResult], history: list[ConversationTurn] | None = None, min_passages: int = 1) -> QueryResponse` — signature extended, fully backward compatible (omitting `history` behaves exactly as before).

- [ ] **Step 1: Write the failing tests**

In `packages/legal_generation/tests/test_generator.py`, add this import alongside the existing ones at the top:

```python
from legal_generation.types import ConversationTurn
```

Then append these two test functions at the end of the file:

```python
async def test_generate_answer_replays_history_as_plain_alternating_messages() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_tool_response(
        {
            "abstained": False,
            "answer": "Pets are allowed, subject to...",
            "used_chunk_ids": ["chunk-1"],
        }
    )
    history = [ConversationTurn(question="what is a tenant?", answer="A tenant is defined as...")]

    with patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client):
        await generate_answer("what about pets?", passages=[PASSAGE], history=history)

    sent_messages = mock_client.messages.create.call_args.kwargs["messages"]
    assert sent_messages[0] == {"role": "user", "content": "what is a tenant?"}
    assert sent_messages[1] == {"role": "assistant", "content": "A tenant is defined as..."}
    assert sent_messages[2]["role"] == "user"
    assert "what about pets?" in sent_messages[2]["content"]


async def test_generate_answer_without_history_sends_a_single_message_as_before() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_tool_response(
        {
            "abstained": False,
            "answer": "A tenant is defined as...",
            "used_chunk_ids": ["chunk-1"],
        }
    )

    with patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client):
        await generate_answer("what is a tenant?", passages=[PASSAGE])

    sent_messages = mock_client.messages.create.call_args.kwargs["messages"]
    assert len(sent_messages) == 1
    assert sent_messages[0]["role"] == "user"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --package legal-generation pytest packages/legal_generation/tests/test_generator.py -v`
Expected: FAIL on `test_generate_answer_replays_history_as_plain_alternating_messages` with `TypeError: generate_answer() got an unexpected keyword argument 'history'`

- [ ] **Step 3: Add the `history` parameter to `generate_answer`**

In `packages/legal_generation/src/legal_generation/generator.py`, add this import:

```python
from legal_generation.types import ConversationTurn
```

Then change:

```python
async def generate_answer(
    question: str,
    passages: list[SearchResult],
    min_passages: int = 1,
) -> QueryResponse:
    if len(passages) < min_passages:
        # Empty/insufficient retrieval is a hard abstain -- not a decision delegated to the
        # model, and Claude is never called at all for this case.
        return _abstain_response()

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        tools=[ANSWER_TOOL],
        tool_choice=ToolChoiceToolParam(type="tool", name="provide_answer"),
        messages=[{"role": "user", "content": _build_prompt(question, passages)}],
    )
```

to:

```python
async def generate_answer(
    question: str,
    passages: list[SearchResult],
    history: list[ConversationTurn] | None = None,
    min_passages: int = 1,
) -> QueryResponse:
    if len(passages) < min_passages:
        # Empty/insufficient retrieval is a hard abstain -- not a decision delegated to the
        # model, and Claude is never called at all for this case. This holds regardless of
        # history -- conversation context doesn't grant license to answer ungrounded (ADR-0003 §4).
        return _abstain_response()

    # Prior turns replay as plain question/answer text, not their original retrieved passage
    # blocks, so context doesn't grow unbounded turn over turn (ADR-0003 §4). Only the current
    # turn's freshly-retrieved passages are included, in the final message, as before.
    messages: list[dict[str, str]] = []
    for turn in history or []:
        messages.append({"role": "user", "content": turn.question})
        messages.append({"role": "assistant", "content": turn.answer})
    messages.append({"role": "user", "content": _build_prompt(question, passages)})

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        tools=[ANSWER_TOOL],
        tool_choice=ToolChoiceToolParam(type="tool", name="provide_answer"),
        messages=messages,
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run --package legal-generation pytest packages/legal_generation/tests/test_generator.py -v`
Expected: all tests in the file pass (8 total: 6 pre-existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add packages/legal_generation/src/legal_generation/generator.py packages/legal_generation/tests/test_generator.py
git commit -m "generate_answer replays conversation history as plain alternating messages"
```

---

### Task 5: Per-turn orchestration (`handle_query_turn`)

**Files:**
- Modify: `packages/legal_generation/pyproject.toml` (add `sqlalchemy[asyncio]` dependency)
- Create: `packages/legal_generation/src/legal_generation/conversation.py`
- Create: `packages/legal_generation/tests/test_conversation.py`

**Interfaces:**
- Consumes: Task 2's `Conversation`/`Message` ORM classes, Task 3's `reformulate_query`/`ConversationTurn`, Task 4's `generate_answer(..., history=...)`, and the existing `legal_retrieval.search.hybrid_search`/`SearchResult`.
- Produces: `legal_generation.conversation.handle_query_turn(session: AsyncSession, question: str, conversation_id: str | None = None, top_k: int = 8, doc_type: str | None = None) -> QueryResponse` (async). Raises `ValueError` if `conversation_id` is given but doesn't exist. Later task (Task 6) calls this directly from the router.

- [ ] **Step 1: Add the `sqlalchemy` dependency to `legal-generation`**

Run: `uv add --package legal-generation "sqlalchemy[asyncio]>=2.0.36"`

- [ ] **Step 2: Write the failing tests**

Create `packages/legal_generation/tests/test_conversation.py`:

```python
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
    _load_conversation's new-conversation branch behaves like it would against a real DB."""
    session = AsyncMock()
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
    session = AsyncMock()
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
    session = AsyncMock()
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
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run --package legal-generation pytest packages/legal_generation/tests/test_conversation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'legal_generation.conversation'`

- [ ] **Step 4: Write `conversation.py`**

Create `packages/legal_generation/src/legal_generation/conversation.py`:

```python
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

    conversation = await session.get(Conversation, uuid.UUID(conversation_id))
    if conversation is None:
        raise ValueError(f"conversation {conversation_id} not found")

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
```

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run --package legal-generation pytest packages/legal_generation/tests/test_conversation.py -v`
Expected: `4 passed`

- [ ] **Step 6: Run the full default suite and lint/typecheck**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy apps packages`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add packages/legal_generation/pyproject.toml uv.lock packages/legal_generation/src/legal_generation/conversation.py packages/legal_generation/tests/test_conversation.py
git commit -m "Add handle_query_turn: per-turn conversation orchestration"
```

---

### Task 6: Wire `POST /query` to `handle_query_turn`

**Files:**
- Modify: `apps/api/src/openlex_api/routers/query.py`
- Modify: `apps/api/tests/test_query.py`

**Interfaces:**
- Consumes: Task 5's `handle_query_turn`.
- Produces: `POST /query` accepts/returns `conversation_id`; returns `404` if an unknown `conversation_id` is given.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `apps/api/tests/test_query.py`:

```python
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
        return_value=QueryResponse(
            answer="", citations=[], abstained=True, conversation_id="abc"
        )
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
        AsyncMock(side_effect=ValueError("conversation abc not found")),
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --package openlex-api pytest apps/api/tests/test_query.py -v`
Expected: FAIL — `openlex_api.routers.query` has no attribute `handle_query_turn` (the router still imports/calls `hybrid_search`/`generate_answer` directly).

- [ ] **Step 3: Rewrite the router**

Replace the entire contents of `apps/api/src/openlex_api/routers/query.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from legal_generation.conversation import handle_query_turn
from legal_models.schemas import QueryRequest, QueryResponse
from openlex_shared.db import get_session
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, session: AsyncSession = Depends(get_session)) -> QueryResponse:
    try:
        return await handle_query_turn(
            session,
            req.question,
            conversation_id=req.conversation_id,
            top_k=req.top_k,
            doc_type=req.doc_type,
        )
    except ValueError as exc:
        # Covers both "conversation_id doesn't exist" and "conversation_id isn't a valid UUID"
        # -- collapsed into one 404 rather than distinguishing 404-vs-400, since the client
        # (this repo's future apps/web) never constructs a malformed conversation_id itself.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run --package openlex-api pytest apps/api/tests/test_query.py -v`
Expected: `5 passed`

- [ ] **Step 5: Run the full default suite and lint/typecheck**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy apps packages`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/openlex_api/routers/query.py apps/api/tests/test_query.py
git commit -m "Wire POST /query to handle_query_turn; add conversation_id 404 mapping"
```

---

### Task 7: CORS for the web frontend

**Files:**
- Modify: `packages/shared/src/openlex_shared/config.py`
- Modify: `apps/api/src/openlex_api/main.py`
- Create: `apps/api/tests/test_cors.py`

**Interfaces:**
- Produces: `openlex_shared.config.Settings.cors_allow_origins: list[str]` (default `["http://localhost:5173"]`); `apps/api` responses include CORS headers for allowed origins.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_cors.py`:

```python
"""Confirms CORSMiddleware is wired up (apps/api/src/openlex_api/main.py) so a web frontend
on a different origin (e.g. :5173, see ADR-0003 §7) can call this API cross-origin."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from openlex_shared.db import get_session

from openlex_api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _mock_db_session():
    async def _get_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _get_session
    yield
    app.dependency_overrides.clear()


def test_allowed_origin_gets_cors_headers() -> None:
    response = client.get("/healthz", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_disallowed_origin_does_not_get_cors_headers() -> None:
    response = client.get("/healthz", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --package openlex-api pytest apps/api/tests/test_cors.py -v`
Expected: FAIL — `test_allowed_origin_gets_cors_headers` fails with a `KeyError` (no `access-control-allow-origin` header present yet).

- [ ] **Step 3: Add `cors_allow_origins` to `Settings`**

In `packages/shared/src/openlex_shared/config.py`, change:

```python
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings fills these from .env at runtime
```

to:

```python
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"

    cors_allow_origins: list[str] = ["http://localhost:5173"]


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings fills these from .env at runtime
```

- [ ] **Step 4: Add `CORSMiddleware` to `main.py`**

In `apps/api/src/openlex_api/main.py`, change the imports:

```python
from fastapi import Depends, FastAPI
from legal_models.schemas import HealthResponse
from legal_retrieval.embeddings import _get_model
from openlex_shared.db import get_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from openlex_api.routers import ingest, query
```

to:

```python
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from legal_models.schemas import HealthResponse
from legal_retrieval.embeddings import _get_model
from openlex_shared.config import settings
from openlex_shared.db import get_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from openlex_api.routers import ingest, query
```

Then change:

```python
app = FastAPI(title="OpenLex API", lifespan=lifespan)
app.include_router(query.router)
app.include_router(ingest.router)
```

to:

```python
app = FastAPI(title="OpenLex API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(query.router)
app.include_router(ingest.router)
```

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run --package openlex-api pytest apps/api/tests/test_cors.py -v`
Expected: `2 passed`

- [ ] **Step 6: Run the full default suite, lint, and typecheck**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy apps packages`
Expected: all green (this plan's final state: default suite fully passing, `tests/evaluation` still deselected as before).

- [ ] **Step 7: Commit**

```bash
git add packages/shared/src/openlex_shared/config.py apps/api/src/openlex_api/main.py apps/api/tests/test_cors.py
git commit -m "Add CORS middleware so a web frontend on another origin can call the API"
```

---

## End-of-plan manual verification

After all 7 tasks are committed, verify the whole multi-turn flow works against a live stack (mirrors the single-shot verification already done for ADR-0002's slice):

```bash
scripts/test-db.sh reset   # picks up both migrations fresh
docker compose up -d db
docker compose up --build -d api worker
scripts/ingest.sh statutes
```

Then:

```bash
# Turn 0 -- omit conversation_id, expect a new one back
curl -s -X POST http://localhost:8000/query -H "Content-Type: application/json" \
  -d '{"question": "What are the grounds for a holdover eviction proceeding?"}' | python3 -m json.tool
```

Copy the `conversation_id` from the response, then:

```bash
# Turn 1 -- a follow-up that only makes sense with turn 0's context
curl -s -X POST http://localhost:8000/query -H "Content-Type: application/json" \
  -d '{"question": "does that include nonpayment of rent?", "conversation_id": "<paste-it-here>"}' \
  | python3 -m json.tool
```

Expect a grounded, relevant answer (not an abstain) referencing RPAPL § 711's nonpayment ground, and the same `conversation_id` echoed back. Also verify the unknown-conversation 404:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "anything", "conversation_id": "00000000-0000-0000-0000-000000000000"}'
# Expect: 404
```

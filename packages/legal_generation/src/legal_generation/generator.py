"""Grounded answer generation -- see the grounded-answer-contract skill.

Two rules are enforced in code, not delegated to the model:
1. Empty/insufficient retrieval is a hard abstain -- Claude is never called at all.
2. Citations are built from OUR OWN retrieval metadata (legal_retrieval.search.SearchResult),
   filtered to the chunk ids the model claims it used -- never from model-generated citation
   text. If the model claims it didn't abstain but cites nothing, we force abstained=True
   server-side anyway (defense in depth -- don't trust the model's flag alone).

`disclaimer` is never part of the tool schema at all, so paraphrasing it is structurally
impossible -- it's always legal_models.schemas.DISCLAIMER via QueryResponse's default.
"""

from pathlib import Path
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam
from legal_models.schemas import Citation, QueryResponse
from legal_retrieval.search import SearchResult
from openlex_shared.config import settings

from legal_generation.types import ConversationTurn

_PROMPT_PATH = Path(__file__).parents[4] / "ml" / "prompts" / "statute_qa_system.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()

ANSWER_TOOL: ToolParam = {
    "name": "provide_answer",
    "description": "Provide a grounded answer using only the provided passages, or abstain.",
    "input_schema": {
        "type": "object",
        "properties": {
            "abstained": {"type": "boolean"},
            "answer": {"type": "string"},
            "used_chunk_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "chunk_id values (from the provided passages) actually relied on for the "
                    "answer; empty if abstained"
                ),
            },
        },
        "required": ["abstained", "answer", "used_chunk_ids"],
    },
}


def _build_prompt(question: str, passages: list[SearchResult]) -> str:
    passage_blocks = "\n\n".join(
        f"[chunk_id: {p.chunk_id}] {p.citation}\n{p.text}" for p in passages
    )
    return _PROMPT_TEMPLATE.format(passages=passage_blocks, question=question)


def _abstain_response() -> QueryResponse:
    return QueryResponse(
        answer=(
            "I don't have enough information in the retrieved statutes to answer this "
            "question responsibly."
        ),
        citations=[],
        abstained=True,
    )


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
    messages_list: list[dict[str, Any]] = []
    for turn in history or []:
        messages_list.append({"role": "user", "content": turn.question})
        messages_list.append({"role": "assistant", "content": turn.answer})
    messages_list.append({"role": "user", "content": _build_prompt(question, passages)})

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        tools=[ANSWER_TOOL],
        tool_choice=ToolChoiceToolParam(type="tool", name="provide_answer"),
        messages=cast(list[MessageParam], messages_list),
    )

    tool_use = next(block for block in response.content if block.type == "tool_use")
    tool_input = cast(dict[str, Any], tool_use.input)

    abstained = bool(tool_input["abstained"])
    used_chunk_ids = set(tool_input["used_chunk_ids"])

    passages_by_id = {p.chunk_id: p for p in passages}
    # Filter against the actual passage id set server-side -- forced tool use doesn't
    # prevent the model from hallucinating a used_chunk_ids value that wasn't provided.
    citations = [
        Citation(
            citation=p.citation,
            doc_type=p.doc_type,
            title=p.title,
            court=p.court,
            date=p.effective_date.isoformat() if p.effective_date else None,
            url=p.url,
            snippet=p.text[:500],
        )
        for chunk_id, p in passages_by_id.items()
        if chunk_id in used_chunk_ids
    ]

    if not abstained and not citations:
        # Contract violation defense: the model answered but cited nothing it was given.
        abstained = True

    if abstained:
        return _abstain_response()

    return QueryResponse(
        answer=str(tool_input["answer"]),
        citations=citations,
        abstained=False,
    )

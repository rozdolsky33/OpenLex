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
        text_block = next(block for block in response.content if block.type == "text")
        return text_block.text.strip()
    except (anthropic.APIError, StopIteration):
        return question

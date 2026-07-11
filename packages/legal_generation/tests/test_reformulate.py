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


async def test_reformulate_query_falls_back_to_raw_question_when_response_has_no_text_block() -> (
    None
):
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = type("Response", (), {"content": []})()
    history = [ConversationTurn(question="what is a tenant?", answer="A tenant is defined as...")]

    with patch("legal_generation.reformulate.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await reformulate_query(history, "what about pets?")

    assert result == "what about pets?"

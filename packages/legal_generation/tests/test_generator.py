from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from legal_generation.generator import generate_answer
from legal_generation.types import ConversationTurn
from legal_retrieval.search import SearchResult

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


def _mock_tool_response(input_dict: dict) -> SimpleNamespace:
    tool_block = SimpleNamespace(type="tool_use", input=input_dict)
    return SimpleNamespace(content=[tool_block])


async def test_generate_answer_abstains_without_calling_claude_when_no_passages() -> None:
    with patch("legal_generation.generator.anthropic.AsyncAnthropic") as mock_anthropic_cls:
        response = await generate_answer("what is the capital of France?", passages=[])

    assert response.abstained is True
    assert response.citations == []
    mock_anthropic_cls.assert_not_called()


async def test_generate_answer_builds_citations_from_search_result_not_model_text() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_tool_response(
        {
            "abstained": False,
            "answer": "A tenant is defined as...",
            "used_chunk_ids": ["chunk-1"],
        }
    )
    with patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client):
        response = await generate_answer("what is a tenant?", passages=[PASSAGE])

    assert response.abstained is False
    assert len(response.citations) == 1
    assert response.citations[0].citation == "RPAPL § 711"
    assert response.citations[0].title == "Grounds where landlord-tenant relationship exists"


async def test_generate_answer_ignores_hallucinated_chunk_ids_not_in_passages() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_tool_response(
        {
            "abstained": False,
            "answer": "A tenant is defined as...",
            "used_chunk_ids": ["chunk-1", "chunk-does-not-exist"],
        }
    )
    with patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client):
        response = await generate_answer("what is a tenant?", passages=[PASSAGE])

    assert len(response.citations) == 1
    assert response.citations[0].citation == "RPAPL § 711"


async def test_generate_answer_forces_abstain_when_model_answers_but_cites_nothing() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_tool_response(
        {"abstained": False, "answer": "Some answer.", "used_chunk_ids": []}
    )
    with patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client):
        response = await generate_answer("what is a tenant?", passages=[PASSAGE])

    assert response.abstained is True
    assert response.citations == []


async def test_generate_answer_respects_model_abstain_flag() -> None:
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = _mock_tool_response(
        {"abstained": True, "answer": "", "used_chunk_ids": []}
    )
    with patch("legal_generation.generator.anthropic.AsyncAnthropic", return_value=mock_client):
        response = await generate_answer("unrelated question", passages=[PASSAGE])

    assert response.abstained is True


async def test_generate_answer_disclaimer_is_always_the_fixed_constant() -> None:
    from legal_models.schemas import DISCLAIMER

    with patch("legal_generation.generator.anthropic.AsyncAnthropic"):
        response = await generate_answer("what is the capital of France?", passages=[])

    assert response.disclaimer == DISCLAIMER


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

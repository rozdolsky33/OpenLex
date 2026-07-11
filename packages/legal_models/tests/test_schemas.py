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

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

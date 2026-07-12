from fastapi import APIRouter, Depends, HTTPException, status
from legal_generation.conversation import ConversationNotFound, handle_query_turn
from legal_models.orm import User
from legal_models.schemas import QueryRequest, QueryResponse
from openlex_shared.db import get_session
from sqlalchemy.ext.asyncio import AsyncSession

from openlex_api.auth import get_current_user
from openlex_api.quota import QuotaExceeded, check_and_consume_quota

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    session: AsyncSession = Depends(get_session),
    # Gates the endpoint on a valid bearer token; not otherwise used by handle_query_turn yet --
    # conversations aren't scoped per-user (any authenticated caller holding a conversation_id
    # can continue it, same accepted limitation ADR-0003 documents for the no-auth case).
    user: User = Depends(get_current_user),
) -> QueryResponse:
    try:
        usage = await check_and_consume_quota(session, user)
    except QuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "tier": exc.tier,
                "limit": exc.limit,
                "reset_at": exc.reset_at.isoformat(),
            },
        ) from exc

    try:
        response = await handle_query_turn(
            session,
            req.question,
            conversation_id=req.conversation_id,
            top_k=req.top_k,
            doc_type=req.doc_type,
        )
    except ConversationNotFound as exc:
        # Covers both "conversation_id doesn't exist" and "conversation_id isn't a valid UUID"
        # -- collapsed into one 404 rather than distinguishing 404-vs-400, since the client
        # (this repo's future apps/web) never constructs a malformed conversation_id itself.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return response.model_copy(update={"usage": usage})

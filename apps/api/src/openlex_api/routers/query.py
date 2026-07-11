from fastapi import APIRouter, Depends
from legal_generation.generator import generate_answer
from legal_models.schemas import QueryRequest, QueryResponse
from legal_retrieval.search import hybrid_search
from openlex_shared.db import get_session
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, session: AsyncSession = Depends(get_session)) -> QueryResponse:
    passages = await hybrid_search(session, req.question, top_k=req.top_k, doc_type=req.doc_type)
    return await generate_answer(req.question, passages)

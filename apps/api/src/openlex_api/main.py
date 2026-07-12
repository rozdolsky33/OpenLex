from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from legal_models.schemas import HealthResponse
from legal_retrieval.embeddings import _get_model
from openlex_shared.config import settings
from openlex_shared.db import get_session
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from openlex_api.routers import auth, ingest, query


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Preload the embedding model once at startup -- don't let the first /healthz call (or
    # the first /query call) be what triggers a multi-second model load.
    _get_model()
    yield


app = FastAPI(title="OpenLex API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(query.router)
app.include_router(ingest.router)


@app.get("/healthz", response_model=HealthResponse)
async def healthz(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    db_ok = False
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    # Checks whether the lifespan hook's preload populated the cache -- never calls
    # _get_model() here, so this stays a cheap probe.
    model_loaded = _get_model.cache_info().currsize > 0

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db=db_ok,
        embedding_model_loaded=model_loaded,
    )


@app.get("/metrics")
async def metrics() -> Response:
    # Minimal, tier-labeled counters only (see openlex_api.quota) -- full auto-instrumented
    # request-latency histograms are a separate, broader observability pass (GA roadmap Phase 3).
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

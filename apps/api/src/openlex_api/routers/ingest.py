from fastapi import APIRouter, HTTPException, status
from legal_models.schemas import IngestRequest

router = APIRouter()


@router.post("/ingest")
async def ingest(req: IngestRequest) -> None:
    # pipelines/ (fetch/normalize/chunk/index) is deliberately worker-only -- it has no
    # pyproject.toml, so apps/api can't cleanly depend on it (see the data-ingestion agent
    # doc). Making that boundary an explicit 501 here, rather than a fragile sys.path/import
    # hack that would only work by accident depending on container layout.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Ingestion runs in the worker container, not via the API. Trigger it with "
            "scripts/compose/ingest.sh (docker compose exec worker ...)."
        ),
    )

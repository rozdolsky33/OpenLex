"""Write normalized+chunked case-law data into Postgres. Thin source-specific wrapper around
pipelines.indexing._shared's write path (dedup/versioning/embed-and-insert-chunks logic
shared with statutes.py) plus the case-specific load -> normalize -> chunk -> index
orchestration. No live fetch step -- see ADR-0006 and pipelines/ingestion/ny_case_law/
loader.py.
"""

from typing import Any

from legal_models.orm import Document
from legal_models.schemas import IngestResponse
from pipelines.indexing._shared import upsert_document
from pipelines.ingestion.ny_case_law.loader import load_seed_cases
from pipelines.normalization.cases import normalize_case
from sqlalchemy.ext.asyncio import AsyncSession

from legal_parsing import ChunkData, chunk_case_text


async def upsert_case_document(
    session: AsyncSession,
    normalized: dict[str, Any],
    chunks: list[ChunkData],
    force: bool = False,
) -> tuple[Document, int]:
    return await upsert_document(session, normalized, chunks, force=force)


async def upsert_all_seed_cases(session: AsyncSession, force: bool = False) -> IngestResponse:
    """Load -> normalize -> chunk -> index every seeded case. No network fetch (unlike
    upsert_all_seed_statutes) -- load_seed_cases() reads seed_cases.json directly.
    Per-document failures are collected into IngestResponse.errors rather than aborting the
    whole batch."""
    documents_ingested = 0
    chunks_created = 0
    errors: list[str] = []

    for raw in load_seed_cases():
        try:
            normalized = normalize_case(raw)
            chunks = chunk_case_text(normalized["text"], citation=normalized["citation"])
            _, n_chunks = await upsert_case_document(session, normalized, chunks, force=force)
            documents_ingested += 1
            chunks_created += n_chunks
        except Exception as exc:  # collected as a per-document error, not raised
            errors.append(f"{raw.get('courtlistener_cluster_id')}: {exc}")

    return IngestResponse(
        status="ok" if not errors else "partial_failure",
        documents_ingested=documents_ingested,
        chunks_created=chunks_created,
        errors=errors,
    )

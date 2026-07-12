"""Write normalized+chunked statute data into Postgres (documents/chunks), respecting the
immutable-versioning rule: an existing (source, source_id, version) row is never updated in
place -- re-ingesting a changed document inserts a new version instead.
"""

from typing import Any

from legal_models.orm import Document
from legal_models.schemas import IngestResponse
from pipelines.indexing._shared import upsert_document
from pipelines.ingestion.ny_legislation.client import fetch_all_seed_statutes
from pipelines.normalization.statutes import normalize_statute
from sqlalchemy.ext.asyncio import AsyncSession

from legal_parsing import ChunkData, chunk_statute_text


async def upsert_statute_document(
    session: AsyncSession,
    normalized: dict[str, Any],
    chunks: list[ChunkData],
    force: bool = False,
) -> tuple[Document, int]:
    """Returns (document_row, chunks_written_count). chunks_written_count is 0 when an
    identical version already exists and force=False (no-op skip). Thin wrapper over
    pipelines.indexing._shared's write path, shared with cases.py's upsert_case_document."""
    return await upsert_document(session, normalized, chunks, force=force)


async def upsert_all_seed_statutes(session: AsyncSession, force: bool = False) -> IngestResponse:
    """Fetch -> normalize -> chunk -> index every seeded statute section. Per-document
    failures are collected into IngestResponse.errors rather than aborting the whole batch."""
    documents_ingested = 0
    chunks_created = 0
    errors: list[str] = []

    raw_statutes = await fetch_all_seed_statutes()
    for raw in raw_statutes:
        try:
            normalized = normalize_statute(raw)
            chunks = chunk_statute_text(normalized["text"], citation=normalized["citation"])
            _, n_chunks = await upsert_statute_document(session, normalized, chunks, force=force)
            documents_ingested += 1
            chunks_created += n_chunks
        except Exception as exc:  # collected as a per-document error, not raised
            errors.append(f"{raw.get('lawId')}/{raw.get('locationId')}: {exc}")

    return IngestResponse(
        status="ok" if not errors else "partial_failure",
        documents_ingested=documents_ingested,
        chunks_created=chunks_created,
        errors=errors,
    )

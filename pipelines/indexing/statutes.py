"""Write normalized+chunked statute data into Postgres (documents/chunks), respecting the
immutable-versioning rule: an existing (source, source_id, version) row is never updated in
place -- re-ingesting a changed document inserts a new version instead.
"""

from typing import Any

from legal_models.orm import Chunk, Document
from legal_models.schemas import IngestResponse
from legal_retrieval.embeddings import embed_passages
from pipelines.ingestion.ny_legislation.client import fetch_all_seed_statutes
from pipelines.normalization.statutes import normalize_statute
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_parsing import ChunkData, chunk_statute_text


async def _latest_existing(session: AsyncSession, source: str, source_id: str) -> Document | None:
    stmt = (
        select(Document)
        .where(Document.source == source, Document.source_id == source_id)
        .order_by(Document.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_statute_document(
    session: AsyncSession,
    normalized: dict[str, Any],
    chunks: list[ChunkData],
    force: bool = False,
) -> tuple[Document, int]:
    """Returns (document_row, chunks_written_count). chunks_written_count is 0 when an
    identical version already exists and force=False (no-op skip)."""
    source = normalized["source"]
    source_id = normalized["source_id"]

    existing = await _latest_existing(session, source, source_id)

    if existing is not None and not force and existing.raw_snapshot == normalized["raw_snapshot"]:
        return existing, 0

    next_version = existing.version + 1 if existing is not None else 1

    document = Document(
        source=source,
        doc_type=normalized["doc_type"],
        jurisdiction=normalized["jurisdiction"],
        citation=normalized["citation"],
        title=normalized["title"],
        source_id=source_id,
        effective_date=normalized["effective_date"],
        version=next_version,
        raw_snapshot=normalized["raw_snapshot"],
        url=normalized["url"],
    )
    session.add(document)
    await session.flush()  # assigns document.id, needed for the chunks' FK below

    embeddings = embed_passages([c.text for c in chunks]) if chunks else []
    for chunk_data, embedding in zip(chunks, embeddings, strict=True):
        session.add(
            Chunk(
                document_id=document.id,
                chunk_index=chunk_data.chunk_index,
                section_label=chunk_data.section_label,
                heading_path=chunk_data.heading_path,
                text=chunk_data.text,
                token_count=chunk_data.token_count,
                embedding=embedding,
            )
        )

    return document, len(chunks)


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

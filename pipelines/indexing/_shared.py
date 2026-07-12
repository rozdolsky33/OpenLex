"""Shared Document+Chunk write path for pipelines/indexing/{statutes,cases}.py: both sources
share the same dedup-by-(source, source_id)/immutable-versioning/embed-and-insert-chunks
logic; only the load/fetch -> normalize -> chunk steps upstream differ per source. Private
module (leading underscore) -- statutes.py/cases.py are the public entry points tests and the
CLI import; this is their shared implementation detail.
"""

from typing import Any

from legal_models.orm import Chunk, Document
from legal_retrieval.embeddings import embed_passages
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_parsing import ChunkData


async def _latest_existing(session: AsyncSession, source: str, source_id: str) -> Document | None:
    stmt = (
        select(Document)
        .where(Document.source == source, Document.source_id == source_id)
        .order_by(Document.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_document(
    session: AsyncSession,
    normalized: dict[str, Any],
    chunks: list[ChunkData],
    force: bool = False,
) -> tuple[Document, int]:
    """Returns (document_row, chunks_written_count); 0 when an identical version already
    exists and force=False. `normalized` is shaped by either normalize_statute or
    normalize_case -- both share the keys used here. `court`/`decision_date` use `.get()`
    because normalize_statute's output never sets them (defaults to None, matching the
    original statute-only behavior exactly)."""
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
        decision_date=normalized.get("decision_date"),
        court=normalized.get("court"),
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

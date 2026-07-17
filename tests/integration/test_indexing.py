import json
from pathlib import Path

from legal_models.orm import Chunk, Document
from pipelines.indexing.statutes import upsert_statute_document
from pipelines.normalization.statutes import normalize_statute
from sqlalchemy import select

from legal_parsing import chunk_statute_text

FIXTURE = Path(__file__).parent.parent / "fixtures" / "rpapl_711_raw.json"


def _normalized_and_chunks() -> tuple[dict, list]:
    raw = json.loads(FIXTURE.read_text())
    normalized = normalize_statute(raw)
    chunks = chunk_statute_text(normalized["text"], citation=normalized["citation"])
    return normalized, chunks


async def test_upsert_statute_document_creates_document_and_chunks(db_session) -> None:
    normalized, chunks = _normalized_and_chunks()

    document, n_chunks, wrote = await upsert_statute_document(db_session, normalized, chunks)

    assert document.version == 1
    assert document.citation == "RPAPL § 711"
    assert n_chunks == len(chunks) == 1
    assert wrote is True

    stored_chunks = (
        (await db_session.execute(select(Chunk).where(Chunk.document_id == document.id)))
        .scalars()
        .all()
    )
    assert len(stored_chunks) == 1
    assert stored_chunks[0].embedding is not None
    assert len(stored_chunks[0].embedding) == 384


async def test_upsert_statute_document_is_idempotent_without_force(db_session) -> None:
    normalized, chunks = _normalized_and_chunks()

    first_doc, _, _ = await upsert_statute_document(db_session, normalized, chunks)
    await db_session.flush()
    second_doc, second_chunks_written, wrote = await upsert_statute_document(
        db_session, normalized, chunks
    )

    assert second_doc.id == first_doc.id
    assert second_doc.version == 1
    assert second_chunks_written == 0
    assert wrote is False

    all_versions = (
        (
            await db_session.execute(
                select(Document).where(
                    Document.source == normalized["source"],
                    Document.source_id == normalized["source_id"],
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(all_versions) == 1


async def test_upsert_statute_document_force_creates_new_version(db_session) -> None:
    normalized, chunks = _normalized_and_chunks()

    first_doc, _, _ = await upsert_statute_document(db_session, normalized, chunks)
    await db_session.flush()
    second_doc, second_chunks_written, wrote = await upsert_statute_document(
        db_session, normalized, chunks, force=True
    )

    assert second_doc.id != first_doc.id
    assert second_doc.version == 2
    assert second_chunks_written == 1
    assert wrote is True

    all_versions = (
        (
            await db_session.execute(
                select(Document).where(
                    Document.source == normalized["source"],
                    Document.source_id == normalized["source_id"],
                )
            )
        )
        .scalars()
        .all()
    )
    assert {d.version for d in all_versions} == {1, 2}

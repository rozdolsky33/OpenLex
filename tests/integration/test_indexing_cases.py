import json
from datetime import date
from pathlib import Path

from legal_models.orm import Chunk, Document
from pipelines.indexing.cases import upsert_case_document
from pipelines.normalization.cases import normalize_case
from sqlalchemy import select

from legal_parsing import chunk_case_text

FIXTURE = Path(__file__).parent.parent / "fixtures" / "park_west_raw.json"


def _normalized_and_chunks() -> tuple[dict, list]:
    raw = json.loads(FIXTURE.read_text())
    normalized = normalize_case(raw)
    chunks = chunk_case_text(normalized["text"], citation=normalized["citation"])
    return normalized, chunks


async def test_upsert_case_document_creates_document_and_chunks(db_session) -> None:
    normalized, chunks = _normalized_and_chunks()

    document, n_chunks = await upsert_case_document(db_session, normalized, chunks)

    assert document.version == 1
    assert document.citation == "47 N.Y.2d 316"
    assert document.court == "New York Court of Appeals"
    assert document.decision_date == date(1979, 6, 7)
    # Proves multi-chunk actually happens for case law, unlike the statute equivalent
    # (test_indexing.py's `n_chunks == len(chunks) == 1`).
    assert n_chunks == len(chunks) > 1

    stored_chunks = (
        (await db_session.execute(select(Chunk).where(Chunk.document_id == document.id)))
        .scalars()
        .all()
    )
    assert len(stored_chunks) == n_chunks
    for chunk in stored_chunks:
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 384


async def test_upsert_case_document_is_idempotent_without_force(db_session) -> None:
    normalized, chunks = _normalized_and_chunks()

    first_doc, _ = await upsert_case_document(db_session, normalized, chunks)
    await db_session.flush()
    second_doc, second_chunks_written = await upsert_case_document(db_session, normalized, chunks)

    assert second_doc.id == first_doc.id
    assert second_doc.version == 1
    assert second_chunks_written == 0

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


async def test_upsert_case_document_force_creates_new_version(db_session) -> None:
    normalized, chunks = _normalized_and_chunks()

    first_doc, _ = await upsert_case_document(db_session, normalized, chunks)
    await db_session.flush()
    second_doc, second_chunks_written = await upsert_case_document(
        db_session, normalized, chunks, force=True
    )

    assert second_doc.id != first_doc.id
    assert second_doc.version == 2
    assert second_chunks_written == len(chunks)

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

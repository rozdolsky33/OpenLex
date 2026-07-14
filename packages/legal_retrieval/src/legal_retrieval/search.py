"""Hybrid retrieval: combines pgvector cosine similarity (HNSW, idx_chunks_embedding) and
Postgres full-text search (GIN, idx_chunks_tsv) via reciprocal rank fusion, per the
openlex-data-model skill's requirement to combine both rather than pick one exclusively.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from legal_retrieval.embeddings import embed_query

_HYBRID_SEARCH_SQL = """
WITH vector_ranked AS (
    SELECT c.id AS chunk_id,
           row_number() OVER (ORDER BY c.embedding <=> CAST(:qvec AS vector)) AS rank
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE (CAST(:doc_type AS text) IS NULL OR d.doc_type = CAST(:doc_type AS text))
    ORDER BY c.embedding <=> CAST(:qvec AS vector)
    LIMIT :candidate_limit
),
fts_ranked AS (
    SELECT c.id AS chunk_id,
           row_number() OVER (
               ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('english', :query_text)) DESC
           ) AS rank
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE (CAST(:doc_type AS text) IS NULL OR d.doc_type = CAST(:doc_type AS text))
      AND c.tsv @@ plainto_tsquery('english', :query_text)
    ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('english', :query_text)) DESC
    LIMIT :candidate_limit
),
fused AS (
    SELECT chunk_id, sum(1.0 / (:rrf_k + rank)) AS score
    FROM (
        SELECT chunk_id, rank FROM vector_ranked
        UNION ALL
        SELECT chunk_id, rank FROM fts_ranked
    ) combined
    GROUP BY chunk_id
),
-- Keep only each document's single best-scoring chunk before ranking for the final top_k.
-- Without this, a long multi-chunk document (case law can run to dozens of chunks) can place
-- several of its own chunks in the top results, crowding out other relevant documents --
-- observed directly against the real corpus: a single case occupied 4 of 8 top-k slots for a
-- generic query, pushing out the actually-relevant statute section entirely. One document can
-- still only contribute one citation to a single hybrid_search call; if it's genuinely the
-- best source, generate_answer's own multi-turn/reformulation flow can surface more of it on
-- a follow-up question.
best_chunk_per_document AS (
    SELECT f.chunk_id, f.score,
           row_number() OVER (
               PARTITION BY c.document_id ORDER BY f.score DESC, f.chunk_id
           ) AS doc_rank
    FROM fused f
    JOIN chunks c ON c.id = f.chunk_id
)
SELECT c.id AS chunk_id, c.document_id, c.text,
       d.citation, d.doc_type, d.title, d.court, d.effective_date, d.url,
       b.score
FROM best_chunk_per_document b
JOIN chunks c ON c.id = b.chunk_id
JOIN documents d ON d.id = c.document_id
WHERE b.doc_rank = 1
-- deterministic tie-break on chunk id: repeated identical queries must return a stable
-- order, or golden-question eval runs aren't reproducible.
ORDER BY b.score DESC, c.id
LIMIT :top_k
"""


@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    text: str
    citation: str
    doc_type: str
    title: str | None
    court: str | None
    effective_date: date | None
    url: str | None
    score: float  # fused RRF score -- for logging/debugging, not user-facing


async def hybrid_search(
    session: AsyncSession,
    query: str,
    top_k: int = 8,
    doc_type: str | None = None,
    rrf_k: int = 60,
    candidate_limit: int = 50,
) -> list[SearchResult]:
    query_vec = embed_query(query)
    vec_literal = "[" + ",".join(str(x) for x in query_vec) + "]"

    rows = (
        await session.execute(
            text(_HYBRID_SEARCH_SQL),
            {
                "qvec": vec_literal,
                "query_text": query,
                "doc_type": doc_type,
                "rrf_k": rrf_k,
                "candidate_limit": candidate_limit,
                "top_k": top_k,
            },
        )
    ).all()

    return [
        SearchResult(
            chunk_id=str(row.chunk_id),
            document_id=str(row.document_id),
            text=row.text,
            citation=row.citation,
            doc_type=row.doc_type,
            title=row.title,
            court=row.court,
            effective_date=row.effective_date,
            url=row.url,
            score=row.score,
        )
        for row in rows
    ]

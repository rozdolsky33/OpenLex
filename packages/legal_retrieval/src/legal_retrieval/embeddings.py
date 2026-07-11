"""Query/passage embedding for hybrid retrieval.

BGE (BAAI/bge-small-en-v1.5, the configured settings.embedding_model_name) is trained
asymmetrically: queries are embedded with an instruction prefix, passages/chunks are embedded
as-is. Getting this backwards measurably hurts retrieval quality -- see
ml/model_cards/bge-small-en-v1.5.md.

Lives here (not in packages/legal_parsing or pipelines/) because both apps/api (embeds the
incoming query at request time) and apps/worker (embeds passages during ingestion) already
depend on legal-retrieval as a workspace package -- see the "next implementation milestone"
plan for the full reasoning.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

from openlex_shared.config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _get_model() -> "SentenceTransformer":
    # Imported lazily so importing this module doesn't force a torch/sentence-transformers
    # load (and the model download) until embeddings are actually needed.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model_name)


def embed_query(text: str) -> list[float]:
    """WITH the BGE asymmetric query-instruction prefix."""
    vec = _get_model().encode(_QUERY_PREFIX + text, normalize_embeddings=True)
    return vec.tolist()


def embed_passage(text: str) -> list[float]:
    """NO prefix -- passages/chunks are embedded as-is per BGE's asymmetric convention."""
    vec = _get_model().encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Batched variant for ingestion throughput. Same no-prefix rule as embed_passage."""
    vecs = _get_model().encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vecs]

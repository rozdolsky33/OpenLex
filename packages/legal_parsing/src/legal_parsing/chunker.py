"""Statute chunking.

v1 ships one chunk per document: NY landlord-tenant statute sections are already narrow
(single numbered sections, not whole articles), so sub-splitting on subsection markers like
"(a)"/"(b)" would add parsing complexity with no demonstrated retrieval-quality need yet.
Revisit only if golden-question evaluation shows retrieval failing on multi-subsection
questions (see tests/evaluation/). `max_tokens` is accepted now and reserved for a future
sub-splitting path so callers won't need to change when v2 lands.

Known limitation: some sections run well past a typical embedding model's max sequence
length (e.g. RPAPL § 711 is ~1000+ words / well over 512 tokens) -- the embedding for such a
chunk will reflect a truncated view of the text (sentence-transformers truncates silently at
the model's max_seq_length). Full-text search (`chunks.tsv`) still covers the whole text
regardless, so hybrid retrieval isn't blind to the truncated portion, only the vector-search
side of it is. Not addressed in this v1 -- see the note above.
"""

from dataclasses import dataclass


@dataclass
class ChunkData:
    chunk_index: int
    section_label: str | None
    heading_path: str | None
    text: str
    token_count: int


def _section_label(citation: str) -> str:
    if "§" in citation:
        return "§" + citation.split("§", 1)[1]
    return citation


def chunk_statute_text(
    text: str,
    citation: str,
    max_tokens: int = 2000,
) -> list[ChunkData]:
    stripped = text.strip()
    return [
        ChunkData(
            chunk_index=0,
            section_label=_section_label(citation),
            heading_path=citation,
            text=stripped,
            token_count=len(stripped.split()),
        )
    ]

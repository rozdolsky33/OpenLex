"""Statute and case-law chunking.

Statutes (chunk_statute_text) ship one chunk per document: NY landlord-tenant statute
sections are already narrow (single numbered sections, not whole articles), so sub-splitting
on subsection markers like "(a)"/"(b)" would add parsing complexity with no demonstrated
retrieval-quality need yet. Revisit only if golden-question evaluation shows retrieval
failing on multi-subsection questions (see tests/evaluation/). `max_tokens` is accepted now
and reserved for a future sub-splitting path so callers won't need to change when v2 lands.

Known limitation: some sections run well past a typical embedding model's max sequence
length (e.g. RPAPL § 711 is ~1000+ words / well over 512 tokens) -- the embedding for such a
chunk will reflect a truncated view of the text (sentence-transformers truncates silently at
the model's max_seq_length). Full-text search (`chunks.tsv`) still covers the whole text
regardless, so hybrid retrieval isn't blind to the truncated portion, only the vector-search
side of it is. Not addressed in this v1 -- see the note above.

Case law (chunk_case_text) cannot reuse the one-chunk-per-document shape: Court of Appeals
opinions run to thousands of words (the consolidated Regina Metropolitan opinion is ~34,000
words), so a single chunk would leave vector search blind to nearly all of a long opinion,
not just truncated the way an oversized statute section is. See ADR-0006.
"""

import re
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


def chunk_case_text(
    text: str,
    citation: str,
    max_tokens: int = 400,
) -> list[ChunkData]:
    """Splits case-law opinion text into multiple chunks on paragraph (blank-line)
    boundaries, packing consecutive paragraphs until adding the next one would exceed
    `max_tokens` (word count, same approximate-not-exact convention as
    chunk_statute_text's token_count). A single paragraph longer than max_tokens is kept
    whole rather than split mid-sentence -- same accepted truncation caveat
    chunk_statute_text already documents for long statute sections, not solved here either.

    max_tokens=400 is a defensible default, not a measured optimum: word count
    under-approximates BGE's subword token count for legal prose, so 400 words leaves
    headroom under bge-small-en-v1.5's ~512-token max_seq_length. See ADR-0006.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paragraphs:
        return []

    grouped: list[str] = []
    current: list[str] = []
    current_word_count = 0
    for para in paragraphs:
        para_word_count = len(para.split())
        if current and current_word_count + para_word_count > max_tokens:
            grouped.append("\n\n".join(current))
            current, current_word_count = [], 0
        current.append(para)
        current_word_count += para_word_count
    if current:
        grouped.append("\n\n".join(current))

    total = len(grouped)
    return [
        ChunkData(
            chunk_index=i,
            section_label=f"{citation} (part {i + 1} of {total})",
            heading_path=citation,
            text=chunk_text,
            token_count=len(chunk_text.split()),
        )
        for i, chunk_text in enumerate(grouped)
    ]

from legal_parsing.chunker import chunk_case_text, chunk_statute_text


def test_chunk_statute_text_returns_one_chunk_per_document_in_v1() -> None:
    chunks = chunk_statute_text("Some statute text.", citation="RPAPL § 711")
    assert len(chunks) == 1


def test_chunk_statute_text_sets_chunk_index_zero() -> None:
    chunks = chunk_statute_text("Some statute text.", citation="RPAPL § 711")
    assert chunks[0].chunk_index == 0


def test_chunk_statute_text_heading_path_is_the_citation() -> None:
    chunks = chunk_statute_text("Some statute text.", citation="RPAPL § 711")
    assert chunks[0].heading_path == "RPAPL § 711"


def test_chunk_statute_text_section_label_is_the_section_number() -> None:
    chunks = chunk_statute_text("Some statute text.", citation="RPAPL § 711")
    assert chunks[0].section_label == "§ 711"


def test_chunk_statute_text_strips_surrounding_whitespace() -> None:
    chunks = chunk_statute_text("  \n  Some statute text.  \n", citation="RPAPL § 711")
    assert chunks[0].text == "Some statute text."


def test_chunk_statute_text_token_count_is_approximate_word_count() -> None:
    chunks = chunk_statute_text("one two three four five", citation="RPAPL § 711")
    assert chunks[0].token_count == 5


def test_chunk_statute_text_handles_citation_without_section_symbol() -> None:
    # e.g. a hypothetical citation missing the "§" separator shouldn't crash the split.
    chunks = chunk_statute_text("Some text.", citation="GOL 7-103")
    assert chunks[0].section_label in ("7-103", "GOL 7-103")


def _paragraphs(n: int, words_per_paragraph: int = 100) -> str:
    return "\n\n".join(" ".join(["word"] * words_per_paragraph) for _ in range(n))


def test_chunk_case_text_splits_on_paragraph_boundaries_when_over_max_tokens() -> None:
    # 5 paragraphs of 100 words each, max_tokens=250 -> packs ~2-3 paragraphs per chunk.
    text = _paragraphs(5, words_per_paragraph=100)
    chunks = chunk_case_text(text, citation="47 N.Y.2d 316", max_tokens=250)
    assert len(chunks) > 1


def test_chunk_case_text_packs_short_paragraphs_into_one_chunk() -> None:
    text = _paragraphs(3, words_per_paragraph=10)
    chunks = chunk_case_text(text, citation="47 N.Y.2d 316", max_tokens=400)
    assert len(chunks) == 1


def test_chunk_case_text_chunk_index_increments() -> None:
    text = _paragraphs(5, words_per_paragraph=100)
    chunks = chunk_case_text(text, citation="47 N.Y.2d 316", max_tokens=250)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_case_text_heading_path_is_the_citation() -> None:
    chunks = chunk_case_text("A single short paragraph.", citation="47 N.Y.2d 316")
    assert chunks[0].heading_path == "47 N.Y.2d 316"


def test_chunk_case_text_section_label_includes_part_number_and_total() -> None:
    text = _paragraphs(5, words_per_paragraph=100)
    chunks = chunk_case_text(text, citation="47 N.Y.2d 316", max_tokens=250)
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        assert chunk.section_label == f"47 N.Y.2d 316 (part {i + 1} of {total})"


def test_chunk_case_text_keeps_an_oversized_single_paragraph_whole() -> None:
    # A paragraph alone longer than max_tokens is still exactly one chunk, not split
    # mid-sentence -- same accepted tradeoff chunk_statute_text documents for long sections.
    text = " ".join(["word"] * 500)
    chunks = chunk_case_text(text, citation="47 N.Y.2d 316", max_tokens=400)
    assert len(chunks) == 1
    assert chunks[0].token_count == 500


def test_chunk_case_text_empty_text_returns_no_chunks() -> None:
    assert chunk_case_text("   \n\n  ", citation="47 N.Y.2d 316") == []

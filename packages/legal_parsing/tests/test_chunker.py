from legal_parsing.chunker import chunk_statute_text


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

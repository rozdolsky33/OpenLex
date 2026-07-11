from legal_retrieval.embeddings import embed_passage, embed_passages, embed_query


def test_embed_query_and_embed_passage_produce_same_dimension() -> None:
    query_vec = embed_query("how much notice before eviction")
    passage_vec = embed_passage("some statute text")
    assert len(query_vec) == len(passage_vec)


def test_embed_query_applies_prefix_so_differs_from_embed_passage_on_same_text() -> None:
    text = "how much notice before eviction"
    assert embed_query(text) != embed_passage(text)


def test_embed_passage_returns_plain_list_of_floats() -> None:
    vec = embed_passage("some statute text")
    assert isinstance(vec, list)
    assert all(isinstance(x, float) for x in vec)


def test_embed_passages_batched_matches_single_embed_passage_dimension() -> None:
    vecs = embed_passages(["text one", "text two"])
    assert len(vecs) == 2
    assert len(vecs[0]) == len(embed_passage("text one"))


def test_embed_passage_is_deterministic() -> None:
    text = "how much notice before eviction"
    assert embed_passage(text) == embed_passage(text)

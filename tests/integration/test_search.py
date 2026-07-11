from legal_retrieval.search import hybrid_search


async def test_hybrid_search_surfaces_relevant_eviction_notice_statutes(
    db_session, seeded_statutes
) -> None:
    results = await hybrid_search(
        db_session, "how much notice must a landlord give before starting an eviction proceeding"
    )
    citations = {r.citation for r in results}
    # RPAPL 711 (the only statute seeded via tests/fixtures/rpapl_711_raw.json) covers the
    # fourteen-day rent-default notice, so it's the relevant hit for this query.
    assert "RPAPL § 711" in citations


async def test_hybrid_search_respects_top_k(db_session, seeded_statutes) -> None:
    results = await hybrid_search(db_session, "landlord tenant", top_k=3)
    assert len(results) <= 3


async def test_hybrid_search_doc_type_filter_excludes_everything_when_no_matching_docs(
    db_session, seeded_statutes
) -> None:
    results = await hybrid_search(db_session, "landlord tenant", doc_type="case")
    assert results == []


async def test_hybrid_search_is_deterministically_ordered(db_session, seeded_statutes) -> None:
    first = await hybrid_search(db_session, "security deposit")
    second = await hybrid_search(db_session, "security deposit")
    assert [r.chunk_id for r in first] == [r.chunk_id for r in second]

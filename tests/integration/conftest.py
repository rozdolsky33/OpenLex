"""Fixtures for tests that hit a real Postgres (see tests/integration/README.md).

Points at a local test database, independent of `openlex_shared.config.settings`'s
`DATABASE_URL` (which resolves to the docker-compose `db` hostname and isn't reachable
outside that network). Point `TEST_DATABASE_URL` at any Postgres+pgvector instance to run
these -- see the repo's infra docs for spinning one up without docker-compose.
"""

import json
import os
from pathlib import Path

import pytest_asyncio
from pipelines.indexing.cases import upsert_case_document
from pipelines.indexing.statutes import upsert_statute_document
from pipelines.normalization.cases import normalize_case
from pipelines.normalization.statutes import normalize_statute
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from legal_parsing import chunk_case_text, chunk_statute_text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://openlex_test@127.0.0.1:5544/openlex_test",
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_statutes(db_session):
    """Ingests the real captured RPAPL 711 fixture via the actual normalize/chunk/index
    pipeline, so search tests exercise the same path production ingestion uses rather than
    hand-built ORM rows."""
    raw = json.loads((FIXTURES_DIR / "rpapl_711_raw.json").read_text())
    normalized = normalize_statute(raw)
    chunks = chunk_statute_text(normalized["text"], citation=normalized["citation"])
    await upsert_statute_document(db_session, normalized, chunks)
    await db_session.flush()
    return db_session


@pytest_asyncio.fixture
async def seeded_cases(db_session):
    """Ingests the synthetic Park West fixture via the actual normalize/chunk/index
    pipeline, mirroring seeded_statutes -- see tests/fixtures/park_west_raw.json's own
    docstring-equivalent comment for why it's synthetic, not the real opinion."""
    raw = json.loads((FIXTURES_DIR / "park_west_raw.json").read_text())
    normalized = normalize_case(raw)
    chunks = chunk_case_text(normalized["text"], citation=normalized["citation"])
    await upsert_case_document(db_session, normalized, chunks)
    await db_session.flush()
    return db_session

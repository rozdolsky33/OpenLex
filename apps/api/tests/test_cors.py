"""Confirms CORSMiddleware is wired up (apps/api/src/openlex_api/main.py) so a web frontend
on a different origin (e.g. :5173, see ADR-0003 §7) can call this API cross-origin."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from openlex_api.main import app
from openlex_shared.db import get_session

client = TestClient(app)


@pytest.fixture(autouse=True)
def _mock_db_session():
    async def _get_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _get_session
    yield
    app.dependency_overrides.clear()


def test_allowed_origin_gets_cors_headers() -> None:
    response = client.get("/healthz", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_disallowed_origin_does_not_get_cors_headers() -> None:
    response = client.get("/healthz", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers

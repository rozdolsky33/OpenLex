"""Tests for GET /healthz (apps/api/src/openlex_api/main.py).

_get_model is patched rather than relying on its real lru_cache state -- other tests in the
same pytest process (e.g. packages/legal_retrieval/tests) may have already populated it, which
would make embedding_model_loaded assertions depend on test execution order.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from openlex_api.main import app
from openlex_shared.db import get_session

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _override_session(session: AsyncMock) -> None:
    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session


def test_healthz_reports_ok_when_db_and_model_are_up() -> None:
    _override_session(AsyncMock())
    with patch("openlex_api.main._get_model") as mock_get_model:
        mock_get_model.cache_info.return_value = SimpleNamespace(currsize=1)
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": True, "embedding_model_loaded": True}


def test_healthz_reports_degraded_when_db_check_fails() -> None:
    session = AsyncMock()
    session.execute.side_effect = ConnectionError("db unreachable")
    _override_session(session)
    with patch("openlex_api.main._get_model") as mock_get_model:
        mock_get_model.cache_info.return_value = SimpleNamespace(currsize=0)
        response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] is False
    assert body["embedding_model_loaded"] is False


def test_healthz_never_triggers_a_model_load_itself() -> None:
    _override_session(AsyncMock())
    with patch("openlex_api.main._get_model") as mock_get_model:
        mock_get_model.cache_info.return_value = SimpleNamespace(currsize=0)
        client.get("/healthz")

    mock_get_model.assert_not_called()
    mock_get_model.cache_info.assert_called()

"""Tests for POST /auth/register and POST /auth/login (apps/api/src/openlex_api/routers/auth.py).

The DB session is overridden with an AsyncMock so these exercise routing/validation/wiring
only -- no real Postgres. session.scalar is patched per-test to stand in for the
select(User).where(...) lookup.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from legal_models.orm import User
from openlex_api.auth import hash_password
from openlex_api.main import app
from openlex_shared.db import get_session

client = TestClient(app)


def _make_user(email: str, password: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        created_at=datetime.now(),
    )


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.add = Mock()  # session.add() is sync on the real AsyncSession

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session
    yield session
    app.dependency_overrides.clear()


def test_register_creates_a_new_user(mock_session) -> None:
    response = client.post(
        "/auth/register", json={"email": "new@example.com", "password": "supersecret"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert "password" not in body
    assert "password_hash" not in body
    mock_session.add.assert_called_once()


def test_register_rejects_duplicate_email(mock_session) -> None:
    mock_session.scalar = AsyncMock(return_value=_make_user("taken@example.com", "whatever123"))
    response = client.post(
        "/auth/register", json={"email": "taken@example.com", "password": "supersecret"}
    )
    assert response.status_code == 409


def test_login_succeeds_with_correct_credentials(mock_session) -> None:
    mock_session.scalar = AsyncMock(return_value=_make_user("tenant@example.com", "correct-pw"))
    response = client.post(
        "/auth/login",
        data={"username": "tenant@example.com", "password": "correct-pw"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_rejects_wrong_password(mock_session) -> None:
    mock_session.scalar = AsyncMock(return_value=_make_user("tenant@example.com", "correct-pw"))
    response = client.post(
        "/auth/login",
        data={"username": "tenant@example.com", "password": "wrong-pw"},
    )
    assert response.status_code == 401


def test_login_rejects_unknown_email(mock_session) -> None:
    response = client.post(
        "/auth/login",
        data={"username": "nobody@example.com", "password": "whatever123"},
    )
    assert response.status_code == 401

"""Tests for POST /auth/login and GET /auth/me (apps/api/src/openlex_api/routers/auth.py).

POST /auth/register is disabled for this demo (see the router's docstring) -- only the seeded
tiered users can log in, so it's tested as an always-403 route rather than a real registration
flow.

The DB session is overridden with an AsyncMock so these exercise routing/validation/wiring
only -- no real Postgres. session.scalar is patched per-test to stand in for the
select(User).where(...) lookup.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from legal_models.orm import User
from legal_models.schemas import UserStatus
from openlex_api.auth import get_current_user, hash_password
from openlex_api.main import app
from openlex_shared.db import get_session

client = TestClient(app)


def _make_user(email: str, password: str, tier: str = "gold") -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        created_at=datetime.now(),
        tier=tier,
        request_count=0,
        period_started_at=datetime.now(UTC),
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


def test_register_is_disabled(mock_session) -> None:
    response = client.post(
        "/auth/register", json={"email": "new@example.com", "password": "supersecret"}
    )
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()
    mock_session.add.assert_not_called()


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


def test_me_returns_current_users_tier_and_usage(mock_session) -> None:
    user = _make_user("jennifer@example.com", "whatever123", tier="platinum")
    app.dependency_overrides[get_current_user] = lambda: user
    expected = UserStatus(
        email=user.email,
        tier="platinum",
        request_count=3,
        request_limit=100,
        period_reset_at=datetime.now(UTC) + timedelta(hours=4),
    )
    with patch("openlex_api.routers.auth.get_user_status", AsyncMock(return_value=expected)):
        response = client.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "platinum"
    assert body["request_count"] == 3
    assert body["request_limit"] == 100


def test_me_requires_authentication() -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401

"""Tests for apps/api/src/openlex_api/quota.py's tier-quota enforcement.

session.execute is patched directly rather than exercised against a real DB (the atomic
UPDATE...WHERE...RETURNING SQL itself is only proven correct against real Postgres -- see
tests/integration for that). These tests cover check_and_consume_quota/get_user_status's own
control flow: what they do with each possible execute() outcome.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from legal_models.orm import User
from openlex_api.quota import (
    QUOTA_PERIOD,
    TIER_LIMITS,
    QuotaExceeded,
    check_and_consume_quota,
    get_user_status,
)


def _make_user(tier: str = "gold", request_count: int = 0, period_started_at=None) -> User:
    return User(
        id=uuid.uuid4(),
        email="steve@example.com",
        password_hash="unused",
        created_at=datetime.now(UTC),
        tier=tier,
        request_count=request_count,
        period_started_at=period_started_at or datetime.now(UTC),
    )


async def test_check_and_consume_quota_increments_and_returns_usage() -> None:
    user = _make_user(tier="gold", request_count=10)
    consume_result = MagicMock()
    consume_result.first.return_value = (user.email, user.tier, 11, user.period_started_at)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[MagicMock(), consume_result])

    usage = await check_and_consume_quota(session, user)

    assert usage.tier == "gold"
    assert usage.request_count == 11
    assert usage.request_limit == TIER_LIMITS["gold"]
    session.commit.assert_awaited_once()


async def test_check_and_consume_quota_raises_when_limit_reached() -> None:
    period_started_at = datetime.now(UTC)
    user = _make_user(
        tier="silver", request_count=TIER_LIMITS["silver"], period_started_at=period_started_at
    )
    consume_result = MagicMock()
    consume_result.first.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[MagicMock(), consume_result])

    exc: QuotaExceeded | None = None
    try:
        await check_and_consume_quota(session, user)
    except QuotaExceeded as e:
        exc = e

    assert exc is not None
    assert exc.tier == "silver"
    assert exc.limit == TIER_LIMITS["silver"]
    assert exc.reset_at == period_started_at + QUOTA_PERIOD
    session.commit.assert_not_awaited()


async def test_get_user_status_reflects_reset_window_without_consuming() -> None:
    user = _make_user(tier="platinum", request_count=42)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())

    async def _refresh(u: User) -> None:
        u.request_count = 0

    session.refresh = AsyncMock(side_effect=_refresh)

    status = await get_user_status(session, user)

    assert status.tier == "platinum"
    assert status.request_count == 0
    assert status.request_limit == TIER_LIMITS["platinum"]
    session.commit.assert_awaited_once()

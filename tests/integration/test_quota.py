"""Integration tests for apps/api/src/openlex_api/quota.py's atomic tier-quota SQL against a
real Postgres -- see tests/integration/README.md for how to run these.

check_and_consume_quota commits internally (by design -- a consumed unit must survive even if
later request handling fails, see the module's own docstring), so unlike this directory's other
tests it can't rely purely on db_session's teardown rollback for cleanup: a commit that already
happened isn't undone by a later rollback. Each test explicitly deletes the user row(s) it
creates and commits that deletion itself.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

from legal_models.orm import User
from openlex_api.quota import QUOTA_PERIOD, TIER_LIMITS, QuotaExceeded, check_and_consume_quota
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://openlex_test@127.0.0.1:5544/openlex_test",
)


def _make_user(tier: str, request_count: int, period_started_at: datetime | None = None) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        password_hash="unused",
        created_at=datetime.now(UTC),
        tier=tier,
        request_count=request_count,
        period_started_at=period_started_at or datetime.now(UTC),
    )


async def test_check_and_consume_quota_increments_a_real_row(db_session) -> None:
    user = _make_user(tier="silver", request_count=TIER_LIMITS["silver"] - 1)
    db_session.add(user)
    await db_session.flush()

    try:
        usage = await check_and_consume_quota(db_session, user)
        assert usage.request_count == TIER_LIMITS["silver"]
        assert usage.request_limit == TIER_LIMITS["silver"]
    finally:
        await db_session.delete(user)
        await db_session.commit()


async def test_check_and_consume_quota_raises_once_the_real_limit_is_hit(db_session) -> None:
    user = _make_user(tier="silver", request_count=TIER_LIMITS["silver"])
    db_session.add(user)
    await db_session.flush()

    try:
        raised = None
        try:
            await check_and_consume_quota(db_session, user)
        except QuotaExceeded as exc:
            raised = exc
        assert raised is not None
        assert raised.limit == TIER_LIMITS["silver"]
    finally:
        await db_session.delete(user)
        await db_session.commit()


async def test_check_and_consume_quota_resets_an_expired_window(db_session) -> None:
    expired_start = datetime.now(UTC) - QUOTA_PERIOD - timedelta(minutes=1)
    user = _make_user(
        tier="gold", request_count=TIER_LIMITS["gold"], period_started_at=expired_start
    )
    db_session.add(user)
    await db_session.flush()

    try:
        usage = await check_and_consume_quota(db_session, user)
        # Window reset zeroed the count before this call's own +1 consumption.
        assert usage.request_count == 1
        assert usage.period_reset_at > datetime.now(UTC)
    finally:
        await db_session.delete(user)
        await db_session.commit()


async def test_concurrent_requests_at_the_boundary_dont_both_succeed(db_session) -> None:
    """Proves the atomic UPDATE...WHERE...RETURNING is actually race-safe against real
    Postgres, not just correct in single-threaded unit tests (see test_quota.py in
    apps/api/tests for the mocked-session control-flow coverage)."""
    user = _make_user(tier="silver", request_count=TIER_LIMITS["silver"] - 1)
    db_session.add(user)
    await db_session.commit()  # both concurrent sessions below need to see this row committed

    engine = create_async_engine(TEST_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _attempt() -> bool:
        async with session_factory() as session:
            row_user = await session.get(User, user.id)
            try:
                await check_and_consume_quota(session, row_user)
                return True
            except QuotaExceeded:
                return False

    try:
        results = await asyncio.gather(_attempt(), _attempt())
        assert sorted(results) == [False, True]
    finally:
        await engine.dispose()
        await db_session.delete(await db_session.get(User, user.id))
        await db_session.commit()

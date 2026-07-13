"""SaaS-tier request quotas for POST /query.

Three fixed tiers (silver/gold/platinum), each with a total request budget that refills on a
rolling window -- not a per-minute burst limiter (that's /auth/login's separate, unrelated
brute-force protection). See docs/superpowers/plans/2026-07-12-ga-readiness-roadmap.md Phase 1
for why this replaced the originally-planned flat per-user rate limit.

Tier limits and the window length are product-level constants, not per-user DB columns --
change them here, not per-row in the database.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from legal_models.orm import User
from legal_models.schemas import UserStatus
from opentelemetry import trace
from prometheus_client import Counter
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

TIER_LIMITS: dict[str, int] = {"silver": 15, "gold": 50, "platinum": 100}
QUOTA_PERIOD = timedelta(hours=4)

QUERY_REQUESTS_TOTAL = Counter(
    "openlex_query_requests_total",
    "Accepted /query calls that consumed a unit of tier quota",
    ["tier"],
)
QUERY_QUOTA_EXCEEDED_TOTAL = Counter(
    "openlex_query_quota_exceeded_total",
    "Rejected /query calls due to the caller's tier quota being exhausted",
    ["tier"],
)


class QuotaExceeded(Exception):
    """Raised when a user has consumed their tier's full request_limit for the current
    QUOTA_PERIOD window. Carries everything apps/api/routers/query.py needs to build the 429
    response body (tier/limit/reset_at) without a second query."""

    def __init__(self, tier: str, limit: int, reset_at: datetime) -> None:
        self.tier = tier
        self.limit = limit
        self.reset_at = reset_at
        super().__init__(f"quota exceeded for tier {tier}: {limit}/{limit} used, resets {reset_at}")


async def _reset_if_expired(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    """Zeroes request_count and restarts the window if it's expired. A no-op UPDATE (0 rows
    affected) if the window is still active. Shared by check_and_consume_quota (which then
    consumes a unit) and get_user_status (which only needs the reset applied, not consumed)."""
    await session.execute(
        update(User)
        .where(User.id == user_id, User.period_started_at <= now - QUOTA_PERIOD)
        .values(request_count=0, period_started_at=now)
    )


async def get_user_status(session: AsyncSession, user: User) -> UserStatus:
    """Read-only equivalent of check_and_consume_quota's window-reset step, for GET /auth/me --
    reflects an expired window without consuming a request unit."""
    now = datetime.now(UTC)
    await _reset_if_expired(session, user.id, now)
    await session.commit()
    await session.refresh(user)

    return UserStatus(
        email=user.email,
        tier=user.tier,
        request_count=user.request_count,
        request_limit=TIER_LIMITS[user.tier],
        period_reset_at=user.period_started_at + QUOTA_PERIOD,
    )


async def check_and_consume_quota(session: AsyncSession, user: User) -> UserStatus:
    """Atomically consumes one unit of `user`'s tier quota, resetting the rolling window first
    if it has expired. Raises QuotaExceeded (without consuming anything) if the user is already
    at their limit for the current window. Commits on success so the consumed unit survives
    even if the caller's later work (retrieval/generation) fails -- quota is not refunded on a
    downstream error, see the roadmap plan's rationale.
    """
    limit = TIER_LIMITS[user.tier]
    now = datetime.now(UTC)

    await _reset_if_expired(session, user.id, now)

    # Atomically consume one unit, guarded by the same WHERE the check reads -- a
    # single UPDATE...WHERE...RETURNING, not read-then-write, so two concurrent requests at
    # `limit - 1` can't both slip through.
    result = await session.execute(
        update(User)
        .where(User.id == user.id, User.request_count < limit)
        .values(request_count=User.request_count + 1)
        .returning(User.email, User.tier, User.request_count, User.period_started_at)
    )
    row = result.first()

    if row is None:
        # Reaching here means step 1 didn't reset the window (it's still active) and the
        # existing request_count is already >= limit -- user.period_started_at (loaded before
        # this call) reflects the current window's start.
        reset_at = user.period_started_at + QUOTA_PERIOD
        _log_quota_event(user.id, user.tier, limit, limit, exceeded=True)
        QUERY_QUOTA_EXCEEDED_TOTAL.labels(tier=user.tier).inc()
        raise QuotaExceeded(tier=user.tier, limit=limit, reset_at=reset_at)

    await session.commit()

    email, tier, request_count, period_started_at = row
    _log_quota_event(user.id, tier, request_count, limit, exceeded=False)
    QUERY_REQUESTS_TOTAL.labels(tier=tier).inc()

    return UserStatus(
        email=email,
        tier=tier,
        request_count=request_count,
        request_limit=limit,
        period_reset_at=period_started_at + QUOTA_PERIOD,
    )


def _log_quota_event(
    user_id: uuid.UUID, tier: str, request_count: int, limit: int, *, exceeded: bool
) -> None:
    # Explicitly embed trace_id in the JSON payload (not just relying on LoggingInstrumentor's
    # surrounding format-string injection -- see apps/api/src/openlex_api/telemetry.py) so Loki
    # can filter/correlate on it as a structured JSON field, not just a substring of the log
    # line. None when there's no active/valid span (e.g. this ever ran outside a request
    # context) -- never crashes on a missing span. PII guardrail: do not add anything else here
    # beyond trace_id -- no question/answer text.
    span_context = trace.get_current_span().get_span_context()
    trace_id = format(span_context.trace_id, "032x") if span_context.is_valid else None
    logger.info(
        json.dumps(
            {
                "event": "query_quota",
                "trace_id": trace_id,
                "user_id": str(user_id),
                "tier": tier,
                "request_count": request_count,
                "request_limit": limit,
                "quota_exceeded": exceeded,
            }
        )
    )

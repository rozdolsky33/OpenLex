"""Seed/refresh the three fixed demo users (Silver/Gold/Platinum) for the tier-quota demo.

Idempotent: upserts by email each run, so `scripts/seed/seed-demo-users.sh` can be rerun to reset a
user's password/tier and zero their quota window for a fresh demo, without a full DB wipe.

Registration is disabled for this demo (see routers/auth.py) -- these three seeded users are
the only accounts that can log in. Run via `scripts/seed/seed-demo-users.sh`.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from legal_models.orm import User
from openlex_shared.config import settings
from openlex_shared.db import SessionLocal
from sqlalchemy import select

from openlex_api.auth import hash_password

DEMO_USERS = [
    ("silver", settings.demo_silver_email, settings.demo_silver_password),
    ("gold", settings.demo_gold_email, settings.demo_gold_password),
    ("platinum", settings.demo_platinum_email, settings.demo_platinum_password),
]


async def seed_demo_users() -> None:
    missing = [
        f"DEMO_{tier.upper()}_EMAIL/DEMO_{tier.upper()}_PASSWORD"
        for tier, email, password in DEMO_USERS
        if not email or not password
    ]
    if missing:
        raise SystemExit(
            "Missing demo user env vars, set these in .env before seeding: " + ", ".join(missing)
        )

    async with SessionLocal() as session:
        for tier, email, password in DEMO_USERS:
            existing = await session.scalar(select(User).where(User.email == email))
            now = datetime.now(UTC)
            if existing is None:
                session.add(
                    User(
                        id=uuid.uuid4(),
                        email=email,
                        password_hash=hash_password(password),
                        created_at=now,
                        tier=tier,
                        request_count=0,
                        period_started_at=now,
                    )
                )
                print(f"created {tier} demo user: {email}")
            else:
                existing.password_hash = hash_password(password)
                existing.tier = tier
                existing.request_count = 0
                existing.period_started_at = now
                print(f"refreshed {tier} demo user: {email}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_demo_users())

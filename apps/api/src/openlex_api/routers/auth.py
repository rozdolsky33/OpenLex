from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from legal_models.orm import User
from legal_models.schemas import Token, UserCreate, UserPublic, UserStatus
from openlex_shared.db import get_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openlex_api.auth import create_access_token, get_current_user, verify_password
from openlex_api.quota import get_user_status

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(req: UserCreate, session: AsyncSession = Depends(get_session)) -> User:
    # Disabled for this demo -- only the seeded tiered users (see
    # apps/api/src/openlex_api/seed_demo_users.py) can log in, so the tier/quota showcase stays
    # focused. The route stays defined (short-circuits before touching the DB) rather than
    # being removed, so re-enabling it later is a one-line revert.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Registration is disabled for this demo",
    )


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> Token:
    incorrect_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = await session.scalar(select(User).where(User.email == form_data.username))
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise incorrect_credentials

    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserStatus)
async def me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserStatus:
    # Read-only: reflects an expired quota window (resets request_count) without consuming a
    # request unit, so opening the app doesn't itself cost against the tier quota.
    return await get_user_status(session, user)

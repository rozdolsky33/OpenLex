# JWT auth for OpenLex POC — design

## Context

OpenLex currently has zero authentication or authorization: no `users` table, no
auth-related dependencies (`jwt`, `bcrypt`, `passlib`, `argon2`, `oauth`, `cors`, or
`middleware` anywhere in `apps/` or `packages/`), and every endpoint (`/query`, `/ingest`,
`/healthz`) is wide open. This is fine for early scaffolding but blocks any kind of
multi-user demo or safe public exposure of the POC. The goal is the smallest JWT-based auth
slice that lets a user register, log in, and get a bearer token that gates the one real
functional endpoint (`POST /query`) — without over-building roles, refresh tokens, or
infrastructure the POC doesn't need yet.

## Decisions

- **Self-service registration** — public `POST /auth/register`, not pre-seeded users.
- **Authentication only, no roles** — any valid JWT grants access; no `role` column or
  admin guard (nothing in the API needs it today).
- **Protects only `POST /query`** — `/healthz` stays public (container health checks),
  `/ingest` is untouched (already a deliberate `501`, worker-only per its docstring).
- **Access token only, no refresh token** — single JWT, 60 minute expiry, HS256. On
  expiry the user just logs in again.
- **`bcrypt` (direct) + `PyJWT`** — not `passlib` (unmaintained, known bcrypt-backend
  version conflicts) and not `argon2` (marginal benefit for a POC, heavier native dep).
- **OAuth2 form login** — `POST /auth/login` uses FastAPI's `OAuth2PasswordRequestForm`
  (form-encoded `username`/`password`), which lights up the "Authorize" button in `/docs`
  so protected endpoints are testable straight from Swagger UI.

## Placement

Follows the existing monorepo split: `packages/legal_models` owns shared domain
models/schemas (mirrors how `Document`/`Chunk` already live there); `apps/api` owns
API-only logic (auth hashing/JWT/dependency, routers) since the worker never
authenticates — no new `packages/legal_auth` package (YAGNI, nothing else consumes it yet).

## Data model

New `migrations/postgres/0002_users.sql`:

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Mirrored in `packages/legal_models/src/legal_models/orm.py` as a `User` class on the
existing `Base`, matching the flat style of `Document`/`Chunk` (no mixins). Pydantic
schemas added to `schemas.py`: `UserCreate` (`email: EmailStr`, `password: str`,
min-length validated), `UserPublic` (`id`, `email`, `created_at` — never
`password_hash`), `Token` (`access_token: str`, `token_type: str = "bearer"`).

## Auth logic (`apps/api/src/openlex_api/auth.py`)

- `hash_password` / `verify_password` using `bcrypt.hashpw`/`bcrypt.checkpw`.
- `create_access_token(user_id)` — JWT with `sub` (user id) and `exp`
  (`now + settings.jwt_expire_minutes`), signed with `settings.jwt_secret_key`/`HS256`.
- `get_current_user(token, session)` — decodes the JWT (401 on invalid/expired
  signature or bad payload), loads the `User` row by id (401 if the user no longer
  exists), returns it. `oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")`
  powers the Swagger "Authorize" button.

## Endpoints (`apps/api/src/openlex_api/routers/auth.py`)

- `POST /auth/register` — body `UserCreate`. 409 if email taken, otherwise hashes
  password, inserts, returns `UserPublic` (201).
- `POST /auth/login` — body `OAuth2PasswordRequestForm` (`username` = email,
  `password`). Generic 401 "Incorrect email or password" for both unknown email and
  wrong password (avoids user enumeration). Returns `Token`.
- `routers/query.py`: `POST /query` gains `user: User = Depends(get_current_user)`
  (auth-only gate, no per-user filtering of results).

## Testing

Follows the existing `test_query.py` pattern: `TestClient(app)`,
`app.dependency_overrides[get_session]` for a fake async session. New
`apps/api/tests/test_auth.py` covers register (success, duplicate email), login
(success, wrong password, unknown email). `test_query.py` gains a case asserting 401
without a token, with `app.dependency_overrides[get_current_user]` used for the existing
success-path tests. Real end-to-end coverage (actual bcrypt hash + real Postgres) is a
natural follow-up for `tests/integration/`, matching how `test_indexing.py` etc. already
test against `db-test`.

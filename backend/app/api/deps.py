"""FastAPI dependencies: the database pool, the signed-in user, and role guards."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.adapters.db import Database
from app.adapters.gemini import GeminiClient, GeminiPort
from app.config import get_settings
from app.modules.me import service as me_service
from app.schemas.me import Role

# Supabase signs access tokens with the project's asymmetric signing key.
JWT_ALGORITHMS = ["ES256", "RS256"]
JWT_AUDIENCE = "authenticated"

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Who a verified access token says the caller is."""

    id: UUID
    email: str | None


@dataclass(frozen=True)
class CurrentUser:
    """The signed-in user; `role` comes from `profiles` and is None until onboarding."""

    id: UUID
    email: str | None
    role: Role | None


def get_db(request: Request) -> Database:
    """The process-wide pool the lifespan opened; 503 when no database is configured."""
    db: Database | None = request.app.state.db
    if db is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database_unavailable")
    return db


@lru_cache
def get_gemini() -> GeminiPort:
    """The process-wide Gemini client, built on first use (building one takes ~0.5 s)."""
    try:
        return GeminiClient(get_settings())
    except ValueError as exc:  # no GEMINI_API_KEY
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "gemini_unavailable") from exc


@lru_cache
def get_jwks_client() -> jwt.PyJWKClient:
    """The project's public signing keys from SUPABASE_JWKS_URL, cached per key id."""
    return jwt.PyJWKClient(get_settings().supabase_jwks_url, cache_keys=True)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    jwks: Annotated[jwt.PyJWKClient, Depends(get_jwks_client)],
) -> AuthenticatedUser:
    """Verify the Supabase access token in `Authorization: Bearer <token>`."""
    if credentials is None:
        raise _unauthorized("not_authenticated")
    token = credentials.credentials
    try:
        # A JWKS cache miss is a blocking HTTP fetch; keep it off the event loop.
        signing_key = await run_in_threadpool(jwks.get_signing_key_from_jwt, token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key,
            algorithms=JWT_ALGORITHMS,
            audience=JWT_AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
        user_id = UUID(claims["sub"])
    except jwt.PyJWKClientConnectionError as exc:
        # Our key fetch failed, not the caller's token: a 401 would sign them out.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth_unavailable") from exc
    except (jwt.PyJWTError, ValueError) as exc:
        raise _unauthorized("invalid_token") from exc
    email = claims.get("email")
    return AuthenticatedUser(id=user_id, email=email if isinstance(email, str) and email else None)


async def current_user(
    user: Annotated[AuthenticatedUser, Depends(authenticated_user)],
    db: Annotated[Database, Depends(get_db)],
) -> CurrentUser:
    """The verified caller plus their role, read from `profiles` (never from the token)."""
    role = await me_service.get_role(db, user.id)
    return CurrentUser(id=user.id, email=user.email, role=role)


def require_role(role: Role) -> Callable[..., Awaitable[CurrentUser]]:
    """A dependency that admits only users with `role`.

    409 `onboarding_required` before the user has chosen a role, 403 `wrong_role`
    for the other role.
    """

    async def dependency(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if user.role is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
        if user.role != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "wrong_role")
        return user

    return dependency

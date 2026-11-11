"""FastAPI dependencies: the database pool, the signed-in user, and role guards."""

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.adapters.claude import ClaudeClient, ClaudePort
from app.adapters.db import Database
from app.adapters.elevenlabs import ElevenLabsClient, ElevenLabsPort
from app.adapters.email import EmailPort, ResendClient
from app.adapters.gemini import GeminiClient, GeminiPort
from app.adapters.paypal import PayPalClient, PayPalPort
from app.adapters.storage import Storage, StoragePort
from app.config import Settings, get_settings
from app.modules.me import service as me_service
from app.schemas.me import Role

# Supabase signs access tokens with the project's asymmetric signing key.
JWT_ALGORITHMS = ["ES256", "RS256"]
JWT_AUDIENCE = "authenticated"
# Clock-skew allowance for `iat`/`exp`/`nbf`. Without it, a server clock that is a few
# seconds behind Supabase's rejects every freshly issued token as "not yet valid".
JWT_LEEWAY_SECONDS = 60

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


def optional_gemini() -> GeminiPort | None:
    """The Gemini client, or None (instead of a 503) when there is no key, for work that
    can proceed without it."""
    try:
        return get_gemini()
    except HTTPException:
        return None


@lru_cache
def get_elevenlabs() -> ElevenLabsPort:
    """The process-wide ElevenLabs client, built on first use."""
    try:
        return ElevenLabsClient(get_settings())
    except ValueError as exc:  # no ELEVENLABS_API_KEY
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "elevenlabs_unavailable") from exc


@lru_cache
def get_email() -> EmailPort:
    """The process-wide Resend client, built on first use."""
    try:
        return ResendClient(get_settings())
    except ValueError as exc:  # no RESEND_API_KEY
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "email_unavailable") from exc


@lru_cache
def get_paypal() -> PayPalPort:
    """The process-wide PayPal sandbox client, built on first use."""
    settings = get_settings()
    try:
        return PayPalClient(
            settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url
        )
    except ValueError as exc:  # no PayPal credentials
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "paypal_unavailable") from exc


@lru_cache
def get_claude() -> ClaudePort:
    """The process-wide Claude client, built on first use."""
    try:
        return ClaudeClient(get_settings().anthropic_api_key)
    except ValueError as exc:  # no ANTHROPIC_API_KEY
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "claude_unavailable") from exc


@lru_cache
def get_storage() -> StoragePort:
    """Supabase Storage for proof screenshots."""
    settings = get_settings()
    try:
        return Storage(settings.supabase_url, settings.supabase_secret_key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "storage_unavailable") from exc


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
            leeway=JWT_LEEWAY_SECONDS,
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


async def onboarded_user(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    """A signed-in user who has chosen a role; 409 `onboarding_required` before that."""
    if user.role is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return user


def require_role(role: Role) -> Callable[..., Awaitable[CurrentUser]]:
    """A dependency that admits only users with `role`.

    409 `onboarding_required` before the user has chosen a role, 403 `wrong_role`
    for the other role.
    """

    async def dependency(user: Annotated[CurrentUser, Depends(onboarded_user)]) -> CurrentUser:
        if user.role != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "wrong_role")
        return user

    return dependency


def require_tool_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    x_collabio_tool_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Admit only the agent's server-tool calls.

    503 `tools_unconfigured` while no secret is set (so an empty header never matches an empty
    secret), 401 `invalid_tool_secret` when the header is missing or wrong.
    """
    expected = settings.elevenlabs_tool_secret
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "tools_unconfigured")
    if x_collabio_tool_secret is None or not hmac.compare_digest(
        x_collabio_tool_secret.encode(), expected.encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_tool_secret")


def require_internal_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Admit only the scheduler (Render cron / workflow). 503 while no secret is set, 401
    when the header is missing or wrong."""
    expected = settings.internal_secret
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "internal_unconfigured")
    if x_internal_secret is None or not hmac.compare_digest(
        x_internal_secret.encode(), expected.encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_internal_secret")

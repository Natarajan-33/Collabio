"""Shared fixtures: the app and its client, test bearer tokens, and the database.

`db` connects to the Supabase Postgres at `SUPABASE_DB_URL`. Tests that use it skip
only when there is no database to use: SUPABASE_DB_URL is empty or still the
dashboard placeholder, or the host cannot be reached. A database that is reachable
but broken (wrong password or database name, missing vector extension, malformed
DSN) fails the tests. Set REQUIRE_DB=1 to turn the skips into failures too, e.g. in CI.
"""

import os
import ssl
import uuid
from collections.abc import AsyncIterator
from typing import NoReturn

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.adapters.db import Database
from app.api.deps import get_db, get_jwks_client
from app.config import get_settings
from app.main import create_app
from tests.tokens import TEST_JWKS, StaticJWKSClient


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def fake_jwks(app: FastAPI) -> None:
    """Verify bearer tokens against TEST_JWKS instead of fetching SUPABASE_JWKS_URL."""
    jwks_client = StaticJWKSClient(TEST_JWKS)
    app.dependency_overrides[get_jwks_client] = lambda: jwks_client


# Database -------------------------------------------------------------------

NOT_CONFIGURED = "database not configured: SUPABASE_DB_URL is empty or a placeholder"
NOT_REACHABLE = "database not reachable"

# The first connect attempt decides for the whole session: later tests reuse its
# outcome instead of reconnecting. A refused connection takes ~2 s on Windows, and
# repeated failed logins can get the client IP banned by the Supabase pooler.
_skip_reason: str | None = None
_connect_failed = False


def _skip(reason: str) -> NoReturn:
    if os.environ.get("REQUIRE_DB") == "1":
        pytest.fail(f"{reason} (REQUIRE_DB=1)", pytrace=False)
    pytest.skip(reason)


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    global _skip_reason, _connect_failed
    if _connect_failed:
        pytest.fail("database connection failed in an earlier test; see that error", pytrace=False)
    if _skip_reason is not None:
        _skip(_skip_reason)

    settings = get_settings()
    if not settings.database_configured:
        _skip_reason = NOT_CONFIGURED
        _skip(NOT_CONFIGURED)

    database = Database()
    try:
        await database.connect(settings.supabase_db_url)
    except Exception as exc:
        # Refused, DNS failure or timeout (TimeoutError is an OSError): no database here.
        if isinstance(exc, OSError) and not isinstance(exc, ssl.SSLError):
            _skip_reason = NOT_REACHABLE
            _skip(NOT_REACHABLE)
        # TLS, auth, catalog, codec or DSN errors: the database is there but broken.
        _connect_failed = True
        raise
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def api_db(app: FastAPI, db: Database) -> Database:
    """Serve the app's requests from the test database (ASGITransport skips the lifespan)."""
    app.dependency_overrides[get_db] = lambda: db
    return db


INSERT_AUTH_USER = (
    "insert into auth.users (id, email, aud, role)"
    " values ($1, $2, 'authenticated', 'authenticated')"
)
DELETE_AUTH_USER = "delete from auth.users where id = $1"


@pytest.fixture
async def auth_user(api_db: Database) -> AsyncIterator[uuid.UUID]:
    """A committed `auth.users` row with no profile yet, as sign-up leaves it.

    The app's requests commit their own transactions, so this row cannot live in a
    rolled-back test transaction. Deleting it afterwards cascades to the profile,
    brand, products and creator row the test created.
    """
    user_id = uuid.uuid4()
    async with api_db.acquire() as conn:
        await conn.execute(INSERT_AUTH_USER, user_id, f"{user_id}@test.collabio.invalid")
    try:
        yield user_id
    finally:
        async with api_db.acquire() as conn:
            await conn.execute(DELETE_AUTH_USER, user_id)

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
from contextlib import asynccontextmanager
from typing import NoReturn

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.adapters.db import Database
from app.api.deps import get_db, get_elevenlabs, get_email, get_gemini, get_jwks_client
from app.config import get_settings
from app.main import create_app
from tests.fakes import FakeElevenLabs, FakeEmail, FakeGemini
from tests.tokens import TEST_JWKS, StaticJWKSClient, auth_header


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


# Seeded demo marketplace ------------------------------------------------------
# These fixtures need the data from `scripts/seed.py`: 40 creators with packages, the
# demo brand and the demo creators. Tests only read it; they never change seeded rows.

NOT_SEEDED = "demo data not seeded: run `uv run python -m scripts.seed --reset`"
DEMO_ARJUN_HANDLE = "arjuntech"
DEMO_PRIYA_HANDLE = "priyareviews"


@pytest.fixture
def fake_gemini(app: FastAPI) -> FakeGemini:
    """Serve embeddings from FakeGemini instead of the Gemini API."""
    gemini = FakeGemini()
    app.dependency_overrides[get_gemini] = lambda: gemini
    return gemini


@pytest.fixture
def fake_elevenlabs(app: FastAPI) -> FakeElevenLabs:
    """Serve Scribe tokens from FakeElevenLabs instead of the ElevenLabs API."""
    elevenlabs = FakeElevenLabs()
    app.dependency_overrides[get_elevenlabs] = lambda: elevenlabs
    return elevenlabs


@pytest.fixture
def fake_email(app: FastAPI) -> FakeEmail:
    """Send email through FakeEmail instead of Resend."""
    email = FakeEmail()
    app.dependency_overrides[get_email] = lambda: email
    return email


async def _auth_user_id(db: Database, email: str) -> uuid.UUID:
    """The seeded demo login with this email, or skip when the seed has not run."""
    if not email:
        _skip(f"{NOT_SEEDED} (a DEMO_* email is not set)")
    async with db.acquire() as conn:
        user_id = await conn.fetchval(
            "select id from auth.users where lower(email) = lower($1)", email
        )
    if user_id is None:
        _skip(NOT_SEEDED)
    return user_id


@asynccontextmanager
async def _signed_in(app: FastAPI, user_id: uuid.UUID) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_header(user_id),
    ) as c:
        yield c


@pytest.fixture
async def brand_client(
    app: FastAPI,
    fake_jwks: None,
    api_db: Database,
    fake_gemini: FakeGemini,
    fake_elevenlabs: FakeElevenLabs,
) -> AsyncIterator[AsyncClient]:
    """A client signed in as the seeded demo brand (Lumen Audio); the voice and search
    services behind it are fakes, so it can never reach a real API."""
    user_id = await _auth_user_id(api_db, get_settings().demo_brand_email)
    async with _signed_in(app, user_id) as c:
        yield c


@pytest.fixture
async def creator_client(
    app: FastAPI, fake_jwks: None, api_db: Database, fake_elevenlabs: FakeElevenLabs
) -> AsyncIterator[AsyncClient]:
    """A client signed in as the seeded demo creator Priya (`priyareviews`). Scribe tokens
    come from a fake; a test that routes voice commands asks for `fake_gemini` itself."""
    user_id = await _auth_user_id(api_db, get_settings().demo_helper_email)
    async with _signed_in(app, user_id) as c:
        yield c


@pytest.fixture
async def other_package_id(api_db: Database) -> uuid.UUID:
    """Another creator's package, for ownership tests: Arjun's cheapest published one."""
    async with api_db.acquire() as conn:
        package_id = await conn.fetchval(
            "select p.id from public.packages p join public.creators c on c.id = p.creator_id"
            " where c.handle = $1 and p.status = 'published'"
            " order by p.base_price_cents, p.name, p.id limit 1",
            DEMO_ARJUN_HANDLE,
        )
    if package_id is None:
        _skip(NOT_SEEDED)
    return package_id


@pytest.fixture
async def new_creator_client(
    app: FastAPI, fake_jwks: None, api_db: Database, fake_gemini: FakeGemini, auth_user: uuid.UUID
) -> AsyncIterator[AsyncClient]:
    """A client signed in as a brand-new creator (niche consumer_tech, no packages, no bio).

    Tests that create, edit, publish or set floors on packages use this instead of the
    seeded creators, whose rows must never change. The creator is onboarded through the
    API; deleting its auth user (the `auth_user` fixture) removes it and its packages.
    Embeddings and structured replies come from `fake_gemini`.
    """
    onboarding = {
        "role": "creator",
        "display_name": "Test Creator",
        "handle": f"test_{auth_user.hex[:12]}",
        "niches": ["consumer_tech"],
        "region": "IN",
    }
    async with _signed_in(app, auth_user) as c:
        r = await c.post("/api/v1/onboarding", json=onboarding)
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
async def new_brand_client(
    app: FastAPI, fake_jwks: None, api_db: Database, auth_user: uuid.UUID
) -> AsyncIterator[AsyncClient]:
    """A client signed in as a brand-new brand with one product and no briefs.

    Used where a test needs a second brand besides the seeded Lumen Audio (ownership
    checks). Deleting its auth user (the `auth_user` fixture) removes it with its briefs.
    """
    onboarding = {
        "role": "brand",
        "display_name": "Test Brand Owner",
        "company_name": "Test Brand Co",
        "category": "consumer_tech",
        "product_name": "Test Product",
        "product_summary": "A test product",
    }
    async with _signed_in(app, auth_user) as c:
        r = await c.post("/api/v1/onboarding", json=onboarding)
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
async def seeded_ids(api_db: Database) -> dict[str, uuid.UUID]:
    """Ids of the two seeded demo creators briefs are written for: Priya and Arjun."""
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select handle, id from public.creators where handle = any($1)",
            [DEMO_PRIYA_HANDLE, DEMO_ARJUN_HANDLE],
        )
    ids = {row["handle"]: row["id"] for row in rows}
    if len(ids) != 2:
        _skip(NOT_SEEDED)
    return {"priya": ids[DEMO_PRIYA_HANDLE], "arjun": ids[DEMO_ARJUN_HANDLE]}


@pytest.fixture
async def brief_cleanup(api_db: Database) -> AsyncIterator[list[str]]:
    """Append the id of every brief a test creates; teardown deletes them, which cascades
    to their batches, threads, events and transcripts. The tests share the hosted database."""
    brief_ids: list[str] = []
    try:
        yield brief_ids
    finally:
        if brief_ids:
            async with api_db.acquire() as conn:
                await conn.execute(
                    "delete from public.briefs where id = any($1::uuid[])", brief_ids
                )

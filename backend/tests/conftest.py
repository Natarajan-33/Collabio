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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.adapters.db import Database
from app.api.deps import (
    get_db,
    get_elevenlabs,
    get_email,
    get_gemini,
    get_jwks_client,
    optional_gemini,
)
from app.config import Settings, get_settings
from app.main import create_app
from app.modules.briefs.service import BriefService
from app.schemas.briefs import LaunchRequest
from tests.api.helpers import delete_try_runs, try_run_events
from tests.fakes import FakeElevenLabs, FakeEmail, FakeGemini
from tests.tokens import TEST_JWKS, StaticJWKSClient, auth_header

# The tests share the hosted database with the dev backend. A lifespan that started the
# launch workers here would claim threads other tests created and could send real email or
# place a real call, so the whole suite runs with workers off. Only a test that opts in
# (tests/api/test_lifespan.py) turns them on, and it patches start_workers/stop_workers.
# Assigned (not setdefault) so a developer's own WORKERS_ENABLED=1 cannot leak in.
os.environ["WORKERS_ENABLED"] = "0"
# The suite's fixtures launch to seeded fictional creators (no account). Tests of production
# behaviour, which hides them, override `demo_mode=False`.
os.environ["DEMO_MODE"] = "1"
get_settings.cache_clear()


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


@pytest.fixture
async def try_runs(api_db: Database, auth_user: uuid.UUID) -> AsyncIterator[uuid.UUID]:
    """The throwaway user a "Try it" demo runs as. Its runs are deleted afterwards, so they
    neither fill the shared database nor count against the demo accounts' daily quota."""
    yield auth_user
    await delete_try_runs(api_db, auth_user)
    assert await try_run_events(api_db, auth_user) == 0


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
    app.dependency_overrides[optional_gemini] = lambda: gemini
    return gemini


@pytest.fixture
def m2_settings(app: FastAPI) -> Settings:
    """Settings with the M2 ElevenLabs and Resend values filled in, served wherever the app
    (or a test) asks for `get_settings` through `Depends`."""
    settings = get_settings().model_copy(
        update={
            "elevenlabs_negotiation_agent_id": "agent_neg",
            "elevenlabs_phone_number_id": "phnum_1",
            "elevenlabs_tool_secret": "tool-secret",
            "elevenlabs_webhook_secret": "hook-secret",
            "elevenlabs_brief_agent_id": "agent_brief",
            "resend_from": "Lumen Audio <outreach@test.collabio.dev>",
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


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


FICTIONAL_HANDLES = ("mayamakestech", "danieldoesdevices")


@pytest.fixture
async def fictional_ids(api_db: Database) -> list[uuid.UUID]:
    """Two seeded creators other than Priya and Arjun, whose email is a reserved
    `@example.com` address. Every launch that succeeds through the API uses only these
    (email channel): a dev worker sharing the database could otherwise claim the threads
    and send real email or place a real call."""
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select handle, id from public.creators"
            " where handle = any($1) and email like '%@example.com'",
            list(FICTIONAL_HANDLES),
        )
    ids = {row["handle"]: row["id"] for row in rows}
    if len(ids) != len(FICTIONAL_HANDLES):
        _skip(NOT_SEEDED)
    return [ids[handle] for handle in FICTIONAL_HANDLES]


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


@dataclass(frozen=True)
class LaunchedBatch:
    brief_id: uuid.UUID
    batch_id: uuid.UUID
    threads: dict[str, uuid.UUID]  # creator handle -> thread id


LAUNCHED_BRIEF = {
    "deliverables_count": 3,
    "deliverables_format": "short_video",
    "budget_ceiling_cents": 123400,  # unusual on purpose, so leak tests can search for it
    "ask_price_cents": 100000,
    "negotiation_ask": "Three short reviews for the Lumen Pods launch",
    "flexibility": ["timeline"],
}


async def _launch_held(
    brand_client: AsyncClient,
    api_db: Database,
    brief_cleanup: list[str],
    channels: dict[uuid.UUID, str],
) -> LaunchedBatch:
    """Create, complete and launch (with `hold=True`) a brief for these creators."""
    created = await brand_client.post(
        "/api/v1/briefs", json={"creator_ids": [str(i) for i in channels]}
    )
    assert created.status_code == 201, created.text
    brief_id = uuid.UUID(created.json()["id"])
    brief_cleanup.append(str(brief_id))
    today = datetime.now(UTC).date()
    patched = await brand_client.patch(
        f"/api/v1/briefs/{brief_id}",
        json=LAUNCHED_BRIEF | {"go_live_by": (today + timedelta(days=30)).isoformat()},
    )
    assert patched.status_code == 200, patched.text

    async with api_db.acquire() as conn:
        brand_id = await conn.fetchval("select brand_id from public.briefs where id = $1", brief_id)
    launched = await BriefService(api_db, brand_id).launch(
        brief_id,
        LaunchRequest(channels=channels),
        today=today,
        embedding=None,
        hold=True,
    )
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select c.handle, t.id from public.threads t join public.creators c on c.id = t.creator_id"
            " where t.batch_id = $1",
            launched.batch_id,
        )
    return LaunchedBatch(
        brief_id=brief_id,
        batch_id=launched.batch_id,
        threads={row["handle"]: row["id"] for row in rows},
    )


@pytest.fixture
async def launched_batch(
    brand_client: AsyncClient,
    api_db: Database,
    brief_cleanup: list[str],
    seeded_ids: dict[str, uuid.UUID],
    fictional_ids: list[uuid.UUID],
) -> LaunchedBatch:
    """A launched batch of three threads: Priya (email), Arjun (call) and Maya (email).

    The brief is created and completed through the API (3 short videos, ask $1,000, private
    ceiling $1,234, go-live in 30 days) and launched with `hold=True`, which parks every thread
    at `next_action_at = 'infinity'` so a running dev worker can never claim it: Arjun's thread
    would otherwise place a real call. The brief is deleted at teardown (`brief_cleanup`).
    """
    priya, arjun, maya = seeded_ids["priya"], seeded_ids["arjun"], fictional_ids[0]
    return await _launch_held(
        brand_client, api_db, brief_cleanup, {arjun: "call", priya: "email", maya: "email"}
    )


@pytest.fixture
async def launched_ten(
    brand_client: AsyncClient,
    api_db: Database,
    brief_cleanup: list[str],
    seeded_ids: dict[str, uuid.UUID],
) -> LaunchedBatch:
    """The `launched_batch` brief over ten seeded fictional creators, all on `email`.

    The creators have `@example.com` addresses, are neither Priya nor Arjun, and have no phone
    opt-in, so no thread can ever send a real email or place a call. Launched with `hold=True`;
    the brief is deleted at teardown (`brief_cleanup`).
    """
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select c.id from public.creators c"
            " where c.email like '%@example.com' and not c.phone_opt_in"
            "   and not c.contact_opt_out and c.id <> all($1::uuid[])"
            "   and exists (select 1 from public.packages p"
            "               where p.creator_id = c.id and p.status = 'published')"
            " order by c.handle limit 10",
            list(seeded_ids.values()),
        )
    if len(rows) < 10:
        _skip(NOT_SEEDED)
    return await _launch_held(
        brand_client, api_db, brief_cleanup, {row["id"]: "email" for row in rows}
    )


@pytest.fixture
def deliverable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat every address as deliverable, so the send path runs even though the seeded
    creators carry reserved `@example.com` addresses. Only FakeEmail ever receives mail, and
    nothing is written to the shared database. Opt-in: request it by name."""
    monkeypatch.setattr(
        "app.modules.outreach.service.is_reserved_address", lambda e: e is None or not e.strip()
    )

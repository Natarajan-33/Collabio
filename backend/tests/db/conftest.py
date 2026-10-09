"""Fixtures for tests that run against the Supabase Postgres at `SUPABASE_DB_URL`.

Every test gets `db_conn`, a connection inside a transaction that is rolled back
afterwards, so seed rows never outlive the test. Rows already in the database
(e.g. the demo seed) stay visible, so tests scope their assertions to the rows
they create (match_creators tests filter on `factory.region`).

The tests skip only when there is no database to use: SUPABASE_DB_URL is empty
or still the dashboard placeholder, or the host cannot be reached. A database
that is reachable but broken (wrong password or database name, missing vector
extension, malformed DSN) fails the tests. Set REQUIRE_DB=1 to turn the skips
into failures too, e.g. in CI.
"""

import json
import os
import ssl
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import NoReturn

import asyncpg
import pytest

from app.adapters.db import Database
from app.config import get_settings

NOT_CONFIGURED = "database not configured: SUPABASE_DB_URL is empty or a placeholder"
NOT_REACHABLE = "database not reachable"
# Supabase dashboard connection strings contain "[YOUR-PASSWORD]" until filled in.
DSN_PLACEHOLDER = "[YOUR-"

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

    dsn = get_settings().supabase_db_url
    if not dsn.strip() or DSN_PLACEHOLDER in dsn:
        _skip_reason = NOT_CONFIGURED
        _skip(NOT_CONFIGURED)

    database = Database()
    try:
        await database.connect(dsn)
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
async def db_conn(db: Database) -> AsyncIterator[asyncpg.Connection]:
    async with db.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn
        finally:
            await tx.rollback()


AsUser = Callable[[asyncpg.Connection, uuid.UUID], Awaitable[None]]


async def _as_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> None:
    """Act as a signed-in user for the rest of the transaction, as PostgREST would."""
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    await conn.execute("select set_config('request.jwt.claims', $1, true)", claims)
    await conn.execute("set local role authenticated")


@pytest.fixture
def as_user() -> AsUser:
    return _as_user


@dataclass(frozen=True)
class Brand:
    id: uuid.UUID
    profile_id: uuid.UUID


@dataclass(frozen=True)
class Creator:
    id: uuid.UUID
    profile_id: uuid.UUID | None


INSERT_AUTH_USER = (
    "insert into auth.users (id, email, aud, role)"
    " values ($1, $2, 'authenticated', 'authenticated')"
)
INSERT_PROFILE = "insert into public.profiles (id, role, display_name) values ($1, $2, $3)"
INSERT_BRAND = "insert into public.brands (profile_id, company_name) values ($1, $2) returning id"
INSERT_PRODUCT = "insert into public.products (brand_id, name) values ($1, $2) returning id"
INSERT_CREATOR = (
    "insert into public.creators"
    " (profile_id, handle, name, niches, region, followers, email, embedding)"
    " values ($1, $2, $3, $4, $5, $6, $7, $8) returning id"
)
INSERT_PACKAGE = (
    "insert into public.packages"
    " (creator_id, name, content_type, niche, volume_count, volume_basis,"
    " base_price_cents, preferred_channel, status)"
    " values ($1, $2, $3, $4, $5, $6, $7, $8, $9) returning id"
)
INSERT_FLOOR = "insert into public.package_floors (package_id, floor_price_cents) values ($1, $2)"


@dataclass
class Factory:
    """Inserts rows through the privileged test connection and returns their ids."""

    conn: asyncpg.Connection
    # Unique per test so search assertions ignore creators already in the database.
    region: str = field(default_factory=lambda: f"test-{uuid.uuid4().hex[:12]}")

    async def user(self, role: str, *, display_name: str = "Test User") -> uuid.UUID:
        """An `auth.users` row plus its profile; returns the user id."""
        user_id = uuid.uuid4()
        await self.conn.execute(INSERT_AUTH_USER, user_id, f"{user_id}@test.collabio.invalid")
        await self.conn.execute(INSERT_PROFILE, user_id, role, display_name)
        return user_id

    async def brand(self) -> Brand:
        profile_id = await self.user("brand")
        brand_id = await self.conn.fetchval(INSERT_BRAND, profile_id, "Test Brand")
        return Brand(id=brand_id, profile_id=profile_id)

    async def product(self, brand_id: uuid.UUID) -> uuid.UUID:
        return await self.conn.fetchval(INSERT_PRODUCT, brand_id, "Test Product")

    async def creator(
        self,
        *,
        login: bool = True,
        followers: int = 10_000,
        niches: Sequence[str] = ("consumer_tech",),
        embedding: list[float] | None = None,
    ) -> Creator:
        """A creator in `self.region`; `login=False` mimics a seeded creator with no account."""
        profile_id = await self.user("creator") if login else None
        handle = f"creator_{uuid.uuid4().hex[:12]}"
        creator_id = await self.conn.fetchval(
            INSERT_CREATOR,
            profile_id,
            handle,
            f"Creator {handle}",
            list(niches),
            self.region,
            followers,
            f"{handle}@test.collabio.invalid",
            embedding,
        )
        return Creator(id=creator_id, profile_id=profile_id)

    async def package(
        self,
        creator_id: uuid.UUID,
        *,
        content_type: str = "short_video",
        volume_count: int = 1,
        volume_basis: str = "per_contract",
        base_price_cents: int = 100_000,
        preferred_channel: str = "email_first",
        status: str = "published",
        floor_price_cents: int | None = None,
    ) -> uuid.UUID:
        package_id = await self.conn.fetchval(
            INSERT_PACKAGE,
            creator_id,
            "Test Package",
            content_type,
            "consumer_tech",
            volume_count,
            volume_basis,
            base_price_cents,
            preferred_channel,
            status,
        )
        if floor_price_cents is not None:
            await self.conn.execute(INSERT_FLOOR, package_id, floor_price_cents)
        return package_id


@pytest.fixture
def factory(db_conn: asyncpg.Connection) -> Factory:
    return Factory(db_conn)

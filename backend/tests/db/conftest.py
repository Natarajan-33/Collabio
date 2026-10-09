"""Fixtures for tests that run against the Supabase Postgres at `SUPABASE_DB_URL`.

Every test gets `db_conn`, a connection inside a transaction that is rolled back
afterwards, so seed rows never outlive the test. Rows already in the database
(e.g. the demo seed) stay visible, so tests scope their assertions to the rows
they create (match_creators tests filter on `factory.region`).

The tests skip when the database cannot be reached, including when the DSN is
still a placeholder.
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import asyncpg
import pytest

from app.adapters.db import Database
from app.config import get_settings

NOT_REACHABLE = "database not reachable"

# Failures that mean "no usable database": a malformed or placeholder DSN
# (ValueError), network errors, timeouts, and server-side refusals.
CONNECT_ERRORS = (ValueError, OSError, TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError)

# Set after the first failed connect so the remaining DB tests skip at once
# (a refused connection takes ~2 s on Windows).
_unreachable = False


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    global _unreachable
    if _unreachable:
        pytest.skip(NOT_REACHABLE)
    database = Database()
    try:
        await database.connect(get_settings().supabase_db_url)
    except CONNECT_ERRORS:
        _unreachable = True
        pytest.skip(NOT_REACHABLE)
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


@dataclass
class Factory:
    """Inserts rows through the privileged test connection and returns their ids."""

    conn: asyncpg.Connection
    # Unique per test so search assertions ignore creators already in the database.
    region: str = field(default_factory=lambda: f"test-{uuid.uuid4().hex[:12]}")

    async def user(self, role: str, *, display_name: str = "Test User") -> uuid.UUID:
        """An `auth.users` row plus its profile; returns the user id."""
        user_id = uuid.uuid4()
        await self.conn.execute(
            "insert into auth.users (id, email, aud, role)"
            " values ($1, $2, 'authenticated', 'authenticated')",
            user_id,
            f"{user_id}@test.collabio.invalid",
        )
        await self.conn.execute(
            "insert into public.profiles (id, role, display_name) values ($1, $2, $3)",
            user_id,
            role,
            display_name,
        )
        return user_id

    async def brand(self) -> Brand:
        profile_id = await self.user("brand")
        brand_id = await self.conn.fetchval(
            "insert into public.brands (profile_id, company_name) values ($1, $2) returning id",
            profile_id,
            "Test Brand",
        )
        return Brand(id=brand_id, profile_id=profile_id)

    async def product(self, brand_id: uuid.UUID) -> uuid.UUID:
        return await self.conn.fetchval(
            "insert into public.products (brand_id, name) values ($1, $2) returning id",
            brand_id,
            "Test Product",
        )

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
            "insert into public.creators"
            " (profile_id, handle, name, niches, region, followers, email, embedding)"
            " values ($1, $2, $3, $4, $5, $6, $7, $8) returning id",
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
        base_price_cents: int = 100_000,
        status: str = "published",
        floor_price_cents: int | None = None,
    ) -> uuid.UUID:
        package_id = await self.conn.fetchval(
            "insert into public.packages"
            " (creator_id, name, content_type, niche, base_price_cents, status)"
            " values ($1, $2, $3, $4, $5, $6) returning id",
            creator_id,
            "Test Package",
            content_type,
            "consumer_tech",
            base_price_cents,
            status,
        )
        if floor_price_cents is not None:
            await self.conn.execute(
                "insert into public.package_floors (package_id, floor_price_cents) values ($1, $2)",
                package_id,
                floor_price_cents,
            )
        return package_id


@pytest.fixture
def factory(db_conn: asyncpg.Connection) -> Factory:
    return Factory(db_conn)

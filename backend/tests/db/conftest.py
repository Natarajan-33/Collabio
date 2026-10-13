"""Fixtures for tests that run against the Supabase Postgres at `SUPABASE_DB_URL`.

Every test gets `db_conn`, a connection inside a transaction that is rolled back
afterwards, so seed rows never outlive the test. Rows already in the database
(e.g. the demo seed) stay visible, so tests scope their assertions to the rows
they create (match_creators tests filter on `factory.region`).

The `db` fixture, and when these tests skip, are in tests/conftest.py.
"""

import json
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import asyncpg
import pytest

from app.adapters.db import Database


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
INSERT_THREAD = (
    "insert into public.threads"
    " (batch_id, brand_id, creator_id, package_id, channel_plan, status, reply_token)"
    " values ($1, $2, $3, $4, $5, $6, $7) returning id"
)
INSERT_EVENT = (
    "insert into public.thread_events"
    " (thread_id, batch_id, brand_id, creator_id, type, actor, payload, external_id)"
    " select t.id, t.batch_id, t.brand_id, t.creator_id, $2, $3, $4::jsonb, $5"
    " from public.threads t where t.id = $1 returning id"
)
INSERT_DEAL = (
    "insert into public.deals"
    " (thread_id, batch_id, brand_id, creator_id, package_id, videos, format, price_cents,"
    " go_live_by, awarded_event_id)"
    " select t.id, t.batch_id, t.brand_id, t.creator_id, t.package_id, $2, 'short_video', $3,"
    " $4, $5 from public.threads t where t.id = $1 returning id"
)
INSERT_MILESTONE = (
    "insert into public.deal_milestones (deal_id, seq, title, amount_cents, due_date)"
    " values ($1, $2, $3, $4, $5)"
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

    async def brief(self, brand: Brand, **cols: object) -> uuid.UUID:
        """A brief for `brand`; `cols` override or add columns (e.g. `status="ready"`)."""
        cols = {"brand_id": brand.id, **cols}
        names = ", ".join(cols)
        marks = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
        return await self.conn.fetchval(
            f"insert into public.briefs ({names}) values ({marks}) returning id", *cols.values()
        )

    async def batch(self, brief_id: uuid.UUID, brand: Brand) -> uuid.UUID:
        return await self.conn.fetchval(
            "insert into public.batches (brief_id, brand_id) values ($1, $2) returning id",
            brief_id,
            brand.id,
        )

    async def thread(
        self,
        batch_id: uuid.UUID,
        brand: Brand,
        creator: Creator,
        package_id: uuid.UUID,
        *,
        status: str = "queued",
        channel_plan: str = "email",
    ) -> uuid.UUID:
        return await self.conn.fetchval(
            INSERT_THREAD,
            batch_id,
            brand.id,
            creator.id,
            package_id,
            channel_plan,
            status,
            secrets.token_urlsafe(24),
        )

    async def event(
        self,
        thread_id: uuid.UUID,
        type: str,
        *,
        actor: str = "system",
        payload: dict[str, object] | None = None,
        external_id: str | None = None,
    ) -> int:
        """An event on a thread; batch, brand and creator are read from the thread."""
        return await self.conn.fetchval(
            INSERT_EVENT, thread_id, type, actor, json.dumps(payload or {}), external_id
        )

    async def deal(
        self,
        thread_id: uuid.UUID,
        *,
        videos: int = 3,
        price_cents: int = 100_000,
        go_live_by: date | None = None,
        milestones: Sequence[int] | None = None,
    ) -> uuid.UUID:
        """An `awarded` event, then a deal for the thread and its milestones, in one transaction.

        `milestones` are the amounts in cents; the default splits the price evenly across
        `videos` (remainder on the last). Pass `[]` to insert the deal alone. The deal's
        milestone check is deferred, so a mismatch only raises at commit (or on
        `set constraints all immediate`).
        """
        go_live = go_live_by or (datetime.now(UTC) + timedelta(days=30)).date()
        amounts = split(price_cents, videos) if milestones is None else list(milestones)
        async with self.conn.transaction():
            event_id = await self.event(thread_id, "awarded", actor="brand")
            deal_id = await self.conn.fetchval(
                INSERT_DEAL, thread_id, videos, price_cents, go_live, event_id
            )
            for seq, amount in enumerate(amounts, start=1):
                await self.conn.execute(
                    INSERT_MILESTONE, deal_id, seq, f"Video {seq}", amount, go_live
                )
        return deal_id


def split(total_cents: int, parts: int) -> list[int]:
    """Even amounts that sum to `total_cents`, the remainder on the last part."""
    each = total_cents // parts
    return [each] * (parts - 1) + [total_cents - each * (parts - 1)]


@pytest.fixture
def factory(db_conn: asyncpg.Connection) -> Factory:
    return Factory(db_conn)

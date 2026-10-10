"""Row-level security on the M1 tables, exercised as the roles PostgREST would use."""

import asyncpg
import pytest

pytestmark = pytest.mark.db

M1_TABLES = ("profiles", "brands", "products", "creators", "packages", "package_floors")


async def ids(conn: asyncpg.Connection, query: str, *args: object) -> set:
    return {row[0] for row in await conn.fetch(query, *args)}


async def test_brand_reads_published_packages_only(db_conn, as_user, factory):
    brand = await factory.brand()
    creator = await factory.creator()
    published = await factory.package(creator.id, status="published")
    await factory.package(creator.id, status="draft")

    await as_user(db_conn, brand.profile_id)

    visible = await ids(db_conn, "select id from public.packages where creator_id = $1", creator.id)
    assert visible == {published}


async def test_creator_reads_own_draft_packages(db_conn, as_user, factory):
    creator = await factory.creator()
    published = await factory.package(creator.id, status="published")
    draft = await factory.package(creator.id, status="draft")

    await as_user(db_conn, creator.profile_id)

    visible = await ids(db_conn, "select id from public.packages where creator_id = $1", creator.id)
    assert visible == {published, draft}


async def test_brand_cannot_read_floors(db_conn, as_user, factory):
    brand = await factory.brand()
    creator = await factory.creator()
    await factory.package(creator.id, floor_price_cents=80_000)

    await as_user(db_conn, brand.profile_id)

    assert await db_conn.fetchval("select count(*) from public.package_floors") == 0


async def test_creator_reads_only_own_floor(db_conn, as_user, factory):
    me = await factory.creator()
    other = await factory.creator()
    mine = await factory.package(me.id, floor_price_cents=80_000)
    await factory.package(other.id, floor_price_cents=90_000)

    await as_user(db_conn, me.profile_id)

    assert await ids(db_conn, "select package_id from public.package_floors") == {mine}


async def test_creators_table_is_owner_only(db_conn, as_user, factory):
    brand = await factory.brand()
    me = await factory.creator()
    await factory.creator()
    await factory.creator(login=False)

    # Brands never read creator rows (they hold contact email/phone) directly.
    await as_user(db_conn, brand.profile_id)
    assert await db_conn.fetchval("select count(*) from public.creators") == 0

    await as_user(db_conn, me.profile_id)
    assert await ids(db_conn, "select id from public.creators") == {me.id}


async def test_profiles_self_only(db_conn, as_user, factory):
    brand = await factory.brand()
    creator = await factory.creator()

    await as_user(db_conn, brand.profile_id)
    assert await ids(db_conn, "select id from public.profiles") == {brand.profile_id}

    await as_user(db_conn, creator.profile_id)
    assert await ids(db_conn, "select id from public.profiles") == {creator.profile_id}


async def test_brands_and_products_owner_only(db_conn, as_user, factory):
    me = await factory.brand()
    other = await factory.brand()
    my_product = await factory.product(me.id)
    await factory.product(other.id)

    await as_user(db_conn, me.profile_id)

    assert await ids(db_conn, "select id from public.brands") == {me.id}
    assert await ids(db_conn, "select id from public.products") == {my_product}


async def test_anon_has_no_access(db_conn):
    await db_conn.execute("set local role anon")

    for table in M1_TABLES:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with db_conn.transaction():  # savepoint: keep the outer transaction usable
                await db_conn.fetch(f"select 1 from public.{table} limit 1")


async def test_clients_cannot_call_match_creators(db_conn, as_user, factory):
    brand = await factory.brand()
    await as_user(db_conn, brand.profile_id)

    # A backend-only search primitive: callers' RLS would hide every creator anyway.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with db_conn.transaction():
            await db_conn.fetch("select * from public.match_creators()")

    await db_conn.execute("set local role anon")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with db_conn.transaction():
            await db_conn.fetch("select * from public.match_creators()")


async def test_authenticated_cannot_write(db_conn, as_user, factory):
    creator = await factory.creator()
    package_id = await factory.package(creator.id)

    await as_user(db_conn, creator.profile_id)

    # Writes go through the backend's privileged connection, never PostgREST.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with db_conn.transaction():
            await db_conn.execute(
                "update public.packages set base_price_cents = 1 where id = $1", package_id
            )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with db_conn.transaction():
            await db_conn.execute(
                "insert into public.package_floors (package_id, floor_price_cents) values ($1, 1)",
                package_id,
            )

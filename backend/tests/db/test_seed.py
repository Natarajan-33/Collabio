"""The seed against the hosted database, inside the rolled-back `db_conn` transaction.

Demo logins are `factory.user` rows (the Auth Admin API half is covered with mocks in
tests/core/test_seed_demo_users.py), so nothing here outlives the test.
"""

import pytest

from scripts.seed import (
    ARJUN_HANDLE,
    PRIYA_HANDLE,
    DemoAccounts,
    DemoUser,
    SeedError,
    plus_address,
    seed_marketplace,
)
from scripts.seed_data import embedding_hash, load_creators, load_embeddings

pytestmark = pytest.mark.db

CREATORS = load_creators()
CACHE = load_embeddings()
HANDLES = [c["handle"] for c in CREATORS]
PRIYA = next(c for c in CREATORS if c["handle"] == PRIYA_HANDLE)
HELPER_EMAIL = "helper.creator@example.com"
HELPER_PHONE = "+15555550123"

SELECT_SEEDED_IDS = "select handle, id from public.creators where handle = any($1::text[])"
COUNT_PACKAGES = """
select count(*) from public.packages p join public.creators c on c.id = p.creator_id
where c.handle = any($1::text[])
"""
COUNT_FLOORS = """
select count(*) from public.package_floors f
join public.packages p on p.id = f.package_id
join public.creators c on c.id = p.creator_id
where c.handle = any($1::text[])
"""
SELECT_CREATOR = "select * from public.creators where handle = $1"


async def demo_accounts(factory) -> DemoAccounts:
    return DemoAccounts(
        brand=DemoUser(
            await factory.user("brand", display_name="Old Name"), "brand-login@example.com"
        ),
        priya=DemoUser(await factory.user("creator"), HELPER_EMAIL),
        arjun=DemoUser(await factory.user("creator"), plus_address(HELPER_EMAIL, "arjun")),
        phone=HELPER_PHONE,
    )


async def seeded_ids(conn) -> dict:
    return {r["handle"]: r["id"] for r in await conn.fetch(SELECT_SEEDED_IDS, HANDLES)}


async def test_seed_is_idempotent_and_searchable(db_conn, factory):
    demo = await demo_accounts(factory)

    assert await seed_marketplace(db_conn, CREATORS, CACHE, demo) == 40
    first_ids = await seeded_ids(db_conn)
    assert await seed_marketplace(db_conn, CREATORS, CACHE, demo) == 40

    packages = sum(len(c["packages"]) for c in CREATORS)
    assert len(first_ids) == 40
    assert await db_conn.fetchval(COUNT_PACKAGES, HANDLES) == packages
    assert await db_conn.fetchval(COUNT_FLOORS, HANDLES) == packages
    # Ids are derived from handles, so a re-seed keeps every creator's id.
    assert await seeded_ids(db_conn) == first_ids

    brands = await db_conn.fetch(
        "select id, company_name, category, contact_email from public.brands where profile_id = $1",
        demo.brand.id,
    )
    assert [(b["company_name"], b["category"], b["contact_email"]) for b in brands] == [
        ("Lumen Audio", "consumer_tech", "brand-login@example.com")
    ]
    products = await db_conn.fetch(
        "select name, summary from public.products where brand_id = $1", brands[0]["id"]
    )
    assert [(p["name"], p["summary"]) for p in products] == [
        ("Lumen Pods", "Wireless earbuds with 40-hour battery and adaptive noise cancelling")
    ]

    priya = await db_conn.fetchrow(SELECT_CREATOR, PRIYA_HANDLE)
    arjun = await db_conn.fetchrow(SELECT_CREATOR, ARJUN_HANDLE)
    assert priya["profile_id"] == demo.priya.id and priya["email"] == HELPER_EMAIL
    assert (priya["phone"], priya["phone_opt_in"]) == (None, False)
    assert arjun["profile_id"] == demo.arjun.id
    assert arjun["email"] == "helper.creator+arjun@example.com"
    assert (arjun["phone"], arjun["phone_opt_in"]) == (HELPER_PHONE, True)
    assert priya["embedding_text_hash"] == embedding_hash(PRIYA)

    rows = await db_conn.fetch(
        "select creator_id, distance from public.match_creators("
        "query_embedding => $1, match_limit => 5)",
        CACHE[embedding_hash(PRIYA)],
    )
    assert rows[0]["creator_id"] == priya["id"]
    assert rows[0]["distance"] < 1e-5 < rows[1]["distance"]


async def test_seed_supports_the_demo_search(db_conn, factory):
    await seed_marketplace(db_conn, CREATORS, CACHE, await demo_accounts(factory))

    rows = await db_conn.fetch(
        "select c.handle from public.match_creators("
        "max_price_cents => 200000, content_types => array['short_video'],"
        " niches => array['consumer_tech'], match_limit => 200) m"
        " join public.creators c on c.id = m.creator_id"
    )

    hits = {r["handle"] for r in rows} & set(HANDLES)
    assert len(hits) >= 12
    assert {ARJUN_HANDLE, PRIYA_HANDLE} <= hits


async def test_seed_without_demo_accounts_leaves_creators_unlinked(db_conn):
    await seed_marketplace(db_conn, CREATORS, CACHE, None)

    priya = await db_conn.fetchrow(SELECT_CREATOR, PRIYA_HANDLE)
    arjun = await db_conn.fetchrow(SELECT_CREATOR, ARJUN_HANDLE)
    assert priya["profile_id"] is None and arjun["profile_id"] is None
    assert (arjun["phone"], arjun["phone_opt_in"]) == (None, False)
    assert priya["email"].endswith("@example.com")


async def test_seed_leaves_other_users_rows_alone(db_conn, factory):
    other_brand = await factory.brand()
    other_product = await factory.product(other_brand.id)
    other_creator = await factory.creator()
    demo = await demo_accounts(factory)
    auth_users_before = await db_conn.fetchval("select count(*) from auth.users")

    await seed_marketplace(db_conn, CREATORS, CACHE, demo)

    assert await db_conn.fetchval("select count(*) from auth.users") == auth_users_before
    assert await db_conn.fetchval("select id from public.brands where id = $1", other_brand.id)
    assert await db_conn.fetchval("select id from public.products where id = $1", other_product)
    assert await db_conn.fetchval("select id from public.creators where id = $1", other_creator.id)


async def test_stale_cache_names_the_creator_and_changes_nothing(db_conn):
    await seed_marketplace(db_conn, CREATORS, CACHE, None)
    before = await seeded_ids(db_conn)
    stale = {h: v for h, v in CACHE.items() if h != embedding_hash(PRIYA)}

    with pytest.raises(
        SeedError,
        match="embedding cache stale for priyareviews — run scripts.build_embedding_cache",
    ):
        await seed_marketplace(db_conn, CREATORS, stale, None)

    assert await seeded_ids(db_conn) == before

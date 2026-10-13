"""Row-level security on the M3 tables: deal parties read, the outbox is backend only."""

import asyncpg
import pytest

pytestmark = pytest.mark.db


async def make_deal(factory):
    brand = await factory.brand()
    creator = await factory.creator()
    package_id = await factory.package(creator.id)
    brief_id = await factory.brief(brand)
    batch_id = await factory.batch(brief_id, brand)
    thread_id = await factory.thread(batch_id, brand, creator, package_id, status="awarded")
    deal_id = await factory.deal(thread_id)
    return brand, creator, thread_id, deal_id


async def readable(conn, table: str) -> list:
    """Rows the current role can read; a refused read counts as none. A savepoint keeps the
    refusal from aborting the surrounding transaction."""
    savepoint = conn.transaction()
    await savepoint.start()
    try:
        return await conn.fetch(f"select * from public.{table}")
    except asyncpg.InsufficientPrivilegeError:
        return []
    finally:
        await savepoint.rollback()


async def test_deal_parties_read_deals_and_milestones(db_conn, as_user, factory):
    brand, creator, _, deal_id = await make_deal(factory)
    other_brand = await factory.brand()
    other_creator = await factory.creator()

    async def visible(profile_id):
        await db_conn.execute("reset role")
        await as_user(db_conn, profile_id)
        deals = {row["id"] for row in await readable(db_conn, "deals")}
        milestones = await readable(db_conn, "deal_milestones")
        return deals, len(milestones)

    assert await visible(brand.profile_id) == ({deal_id}, 3)
    assert await visible(creator.profile_id) == ({deal_id}, 3)
    assert await visible(other_brand.profile_id) == (set(), 0)
    assert await visible(other_creator.profile_id) == (set(), 0)


async def test_outbox_unreadable(db_conn, as_user, factory):
    brand, creator, thread_id, _ = await make_deal(factory)
    event_id = await factory.event(thread_id, "accepted", actor="creator")
    await db_conn.execute(
        "insert into public.outbox_emails (kind, thread_id, event_id, to_role)"
        " values ('brand_creator_accepted', $1, $2, 'brand')",
        thread_id,
        event_id,
    )

    for profile_id in (brand.profile_id, creator.profile_id):
        await db_conn.execute("reset role")
        await as_user(db_conn, profile_id)
        assert await readable(db_conn, "outbox_emails") == []


async def test_anon_reads_no_deals(db_conn, factory):
    await make_deal(factory)

    await db_conn.execute("set local role anon")

    for table in ("deals", "deal_milestones", "outbox_emails"):
        assert await readable(db_conn, table) == [], f"anon can read {table}"

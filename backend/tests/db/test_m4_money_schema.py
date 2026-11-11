"""M4 schema invariants: money tables, append-only ledger, status checks, RLS."""

import asyncpg
import pytest

from tests.db.test_rls_m3 import make_deal, readable

pytestmark = pytest.mark.db

NEW_TABLES = (
    "deal_bonus_terms",
    "deal_funding",
    "milestone_submissions",
    "settlement_runs",
    "payouts",
    "money_events",
    "usage_counters",
)


async def first_milestone(conn, deal_id):
    return await conn.fetchval(
        "select id from public.deal_milestones where deal_id = $1 order by seq limit 1", deal_id
    )


async def insert_payout(conn, milestone_id, sender_batch_id, amount=1000):
    return await conn.fetchval(
        "insert into public.payouts (milestone_id, amount_cents, status, sender_batch_id)"
        " values ($1, $2, 'awaiting_approval', $3) returning id",
        milestone_id,
        amount,
        sender_batch_id,
    )


async def test_new_tables_exist(db_conn):
    for table in NEW_TABLES:
        assert await db_conn.fetchval("select to_regclass($1) is not null", f"public.{table}")
    cols = await db_conn.fetch(
        "select table_name, column_name from information_schema.columns where table_schema ="
        " 'public' and ((table_name = 'brands' and column_name = 'auto_approve_limit_cents')"
        " or (table_name = 'creators' and column_name = 'payout_email'))"
    )
    assert len(cols) == 2


async def test_auto_approve_limit_defaults_and_bounds(db_conn, factory):
    brand = await factory.brand()
    assert (
        await db_conn.fetchval(
            "select auto_approve_limit_cents from public.brands where id = $1", brand.id
        )
        == 30000
    )
    with pytest.raises(asyncpg.CheckViolationError):
        async with db_conn.transaction():
            await db_conn.execute(
                "update public.brands set auto_approve_limit_cents = 1000001 where id = $1",
                brand.id,
            )


async def test_money_events_rejects_update(db_conn, factory):
    _, _, _, deal_id = await make_deal(factory)
    event_id = await db_conn.fetchval(
        "insert into public.money_events (deal_id, kind, amount_cents) values ($1, 'funded', 100)"
        " returning id",
        deal_id,
    )
    with pytest.raises(asyncpg.RaiseError):
        async with db_conn.transaction():
            await db_conn.execute(
                "update public.money_events set amount_cents = 5 where id = $1", event_id
            )
    with pytest.raises(asyncpg.RaiseError):
        async with db_conn.transaction():
            await db_conn.execute("delete from public.money_events where id = $1", event_id)


async def test_money_events_delete_allowed_during_demo_reset(db_conn, factory):
    _, _, _, deal_id = await make_deal(factory)
    await db_conn.execute(
        "insert into public.money_events (deal_id, kind, amount_cents) values ($1, 'funded', 100)",
        deal_id,
    )
    async with db_conn.transaction():
        await db_conn.execute("set local collabio.demo_reset = 'on'")
        await db_conn.execute("delete from public.money_events where deal_id = $1", deal_id)
    assert await db_conn.fetchval(
        "select count(*) from public.money_events where deal_id = $1", deal_id
    ) == 0


async def test_payout_sender_batch_id_unique(db_conn, factory):
    _, _, _, deal_id = await make_deal(factory)
    milestone_id = await first_milestone(db_conn, deal_id)
    await insert_payout(db_conn, milestone_id, "collabio-x")
    with pytest.raises(asyncpg.UniqueViolationError):
        async with db_conn.transaction():
            await insert_payout(db_conn, milestone_id, "collabio-x")


async def test_deal_status_accepts_funded_completed(db_conn, factory):
    _, _, _, deal_id = await make_deal(factory)
    for status in ("funded", "completed"):
        await db_conn.execute("update public.deals set status = $2 where id = $1", deal_id, status)
    milestone_id = await first_milestone(db_conn, deal_id)
    for status in ("funded", "submitted", "needs_changes", "verified", "paid"):
        await db_conn.execute(
            "update public.deal_milestones set status = $2 where id = $1", milestone_id, status
        )
    with pytest.raises(asyncpg.CheckViolationError):
        async with db_conn.transaction():
            await db_conn.execute(
                "update public.deals set status = 'bogus' where id = $1", deal_id
            )


async def test_brand_cannot_read_other_brands_payouts(db_conn, as_user, factory):
    brand, creator, _, deal_id = await make_deal(factory)
    other_brand = await factory.brand()
    milestone_id = await first_milestone(db_conn, deal_id)
    await insert_payout(db_conn, milestone_id, "collabio-rls")
    await db_conn.execute(
        "insert into public.money_events (deal_id, kind, amount_cents) values ($1, 'funded', 100)",
        deal_id,
    )

    async def visible(profile_id):
        await db_conn.execute("reset role")
        await as_user(db_conn, profile_id)
        return (
            len(await readable(db_conn, "payouts")),
            len(await readable(db_conn, "money_events")),
            len(await readable(db_conn, "usage_counters")),
        )

    assert await visible(brand.profile_id) == (1, 1, 0)
    assert await visible(creator.profile_id) == (1, 1, 0)
    assert await visible(other_brand.profile_id) == (0, 0, 0)
    await db_conn.execute("reset role")

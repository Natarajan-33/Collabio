"""The money demo seed (spec §9): three fictional deals, idempotent, reset-safe."""

import pytest

from app.config import get_settings
from scripts.seed_money import DEMO_TITLES, seed_money

pytestmark = pytest.mark.db


async def counts(conn, brand_id):
    return await conn.fetchrow(
        "select count(*) filter (where true) as deals,"
        " count(*) filter (where d.status = 'booked') as booked,"
        " count(*) filter (where d.status = 'funded') as funded,"
        " count(*) filter (where d.status = 'completed') as completed"
        " from public.deals d join public.batches b on b.id = d.batch_id"
        " join public.briefs br on br.id = b.brief_id"
        " where d.brand_id = $1 and br.flexibility_note = 'collabio-demo-money'",
        brand_id,
    )


async def test_seed_money_idempotent(db_conn):
    if not get_settings().demo_brand_email:
        pytest.skip("demo accounts are not configured")
    first = await seed_money(db_conn)
    second = await seed_money(db_conn)
    assert set(first) == set(DEMO_TITLES) == set(second)
    brand_id = await db_conn.fetchval(
        "select d.brand_id from public.deals d where d.id = $1", second["Lumen Pods launch"]
    )
    row = await counts(db_conn, brand_id)
    assert (row["deals"], row["booked"], row["funded"], row["completed"]) == (3, 1, 1, 1)
    # Studio Monitors: one payout paid, one waiting for approval; seed rows are labelled.
    payouts = await db_conn.fetch(
        "select p.status from public.payouts p join public.deal_milestones m"
        " on m.id = p.milestone_id where m.deal_id = $1 order by m.seq",
        second["Studio Monitors"],
    )
    assert [p["status"] for p in payouts] == ["success", "awaiting_approval"]
    refs = await db_conn.fetch(
        "select paypal_ref from public.money_events where deal_id = $1 and paypal_ref is not null",
        second["Desk Speaker"],
    )
    assert refs and all(r["paypal_ref"].startswith("SEED-") for r in refs)


async def test_seeded_briefs_have_an_asking_price(db_conn):
    """Offers list computes a delta from the brief's ask; a null ask 500s the brand's offers."""
    if not get_settings().demo_brand_email:
        pytest.skip("demo accounts are not configured")
    await seed_money(db_conn)
    rows = await db_conn.fetch(
        "select ask_price_cents from public.briefs where flexibility_note = 'collabio-demo-money'"
    )
    assert rows and all(r["ask_price_cents"] for r in rows)

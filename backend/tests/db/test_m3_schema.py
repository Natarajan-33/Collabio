"""M3 schema invariants: hire targets, offer expiry, deals and their milestones, the outbox."""

import asyncpg
import pytest

pytestmark = pytest.mark.db


async def make_thread(factory, *, status: str = "queued"):
    brand = await factory.brand()
    creator = await factory.creator()
    package_id = await factory.package(creator.id)
    brief_id = await factory.brief(brand)
    batch_id = await factory.batch(brief_id, brand)
    return await factory.thread(batch_id, brand, creator, package_id, status=status)


async def test_hires_target_defaults_and_bounds(db_conn, factory):
    brand = await factory.brand()
    brief_id = await factory.brief(brand)
    batch_id = await factory.batch(brief_id, brand)

    row = await db_conn.fetchrow(
        "select br.hires_target as brief_target, b.hires_target as batch_target,"
        " b.offer_ttl_days from public.briefs br, public.batches b"
        " where br.id = $1 and b.id = $2",
        brief_id,
        batch_id,
    )
    assert (row["brief_target"], row["batch_target"], row["offer_ttl_days"]) == (1, 1, 7)

    for bad in (0, 11):
        with pytest.raises(asyncpg.CheckViolationError):
            async with db_conn.transaction():
                await db_conn.execute(
                    "update public.briefs set hires_target = $2 where id = $1", brief_id, bad
                )
        with pytest.raises(asyncpg.CheckViolationError):
            async with db_conn.transaction():
                await db_conn.execute(
                    "update public.batches set hires_target = $2 where id = $1", batch_id, bad
                )


async def test_offer_expired_event_allowed(db_conn, factory):
    thread_id = await make_thread(factory)

    event_id = await factory.event(thread_id, "offer_expired")

    assert isinstance(event_id, int)


async def test_deal_requires_matching_milestones(db_conn, factory):
    thread_id = await make_thread(factory)
    await factory.deal(thread_id, videos=3, price_cents=100_000, milestones=[33_333] * 3)

    with pytest.raises(asyncpg.RaiseError, match="milestones"):
        await db_conn.execute("set constraints all immediate")


async def test_deal_with_matching_milestones_commits(db_conn, factory):
    thread_id = await make_thread(factory)
    deal_id = await factory.deal(thread_id, videos=3, price_cents=100_000)

    await db_conn.execute("set constraints all immediate")

    amounts = await db_conn.fetchval(
        "select array_agg(amount_cents order by seq) from public.deal_milestones"
        " where deal_id = $1",
        deal_id,
    )
    assert amounts == [33_333, 33_333, 33_334]


async def test_deal_without_milestones_rejected(db_conn, factory):
    thread_id = await make_thread(factory)
    await factory.deal(thread_id, milestones=[])

    with pytest.raises(asyncpg.RaiseError, match="milestones"):
        await db_conn.execute("set constraints all immediate")


async def test_deal_terms_immutable(db_conn, factory):
    thread_id = await make_thread(factory)
    deal_id = await factory.deal(thread_id)

    with pytest.raises(asyncpg.RaiseError, match="immutable"):
        async with db_conn.transaction():
            await db_conn.execute("update public.deals set price_cents = 1 where id = $1", deal_id)
    with pytest.raises(asyncpg.RaiseError, match="immutable"):
        async with db_conn.transaction():
            await db_conn.execute(
                "update public.deal_milestones set amount_cents = 100 where deal_id = $1", deal_id
            )

    result = await db_conn.execute(
        "update public.deals set status = 'booked' where id = $1", deal_id
    )
    assert result == "UPDATE 1"


async def test_one_deal_per_thread(db_conn, factory):
    thread_id = await make_thread(factory)
    await factory.deal(thread_id)

    with pytest.raises(asyncpg.UniqueViolationError):
        await factory.deal(thread_id)


async def test_outbox_unique_per_kind_and_event(db_conn, factory):
    thread_id = await make_thread(factory)
    event_id = await factory.event(thread_id, "accepted", actor="creator")
    insert = (
        "insert into public.outbox_emails (kind, thread_id, event_id, to_role)"
        " values ($1, $2, $3, $4)"
    )
    await db_conn.execute(insert, "brand_creator_accepted", thread_id, event_id, "brand")

    # A different kind for the same event is a different notification.
    await db_conn.execute(insert, "creator_closed", thread_id, event_id, "creator")
    with pytest.raises(asyncpg.UniqueViolationError):
        await db_conn.execute(insert, "brand_creator_accepted", thread_id, event_id, "brand")


async def test_match_creators_registered_only(db_conn):
    query = (
        "select m.creator_id, c.profile_id from public.match_creators("
        "registered_only => $1, match_limit => 1000) m"
        " join public.creators c on c.id = m.creator_id"
    )
    only = await db_conn.fetch(query, True)
    every = await db_conn.fetch(query, False)

    assert all(row["profile_id"] is not None for row in only)
    assert any(row["profile_id"] is None for row in every)
    assert len(every) > len(only)


async def test_transcripts_have_a_nullable_raw_text(db_conn, factory):
    thread_id = await make_thread(factory)

    row = await db_conn.fetchrow(
        "insert into public.transcripts (thread_id, kind, external_id, body_text)"
        " values ($1, 'email_in', $2, 'hi') returning raw_text",
        thread_id,
        f"rcv_{thread_id}",
    )

    assert row["raw_text"] is None
    await db_conn.execute(
        "update public.transcripts set raw_text = 'hi\n> quoted' where thread_id = $1", thread_id
    )
    assert (
        await db_conn.fetchval(
            "select raw_text from public.transcripts where thread_id = $1", thread_id
        )
        == "hi\n> quoted"
    )


async def test_inbound_raw_migration_backfills_open_offers_expiry(db_conn, factory):
    from pathlib import Path

    sql = Path("supabase/migrations/20261015120000_m3_inbound_raw.sql").read_text()
    backfill = sql[sql.index("update public.threads") :]
    waiting = await make_thread(factory, status="awaiting_reply")
    queued = await make_thread(factory, status="queued")

    await db_conn.execute(backfill)

    rows = await db_conn.fetch(
        "select t.id, t.expires_at, t.expires_at - now() as left_, b.offer_ttl_days"
        " from public.threads t join public.batches b on b.id = t.batch_id"
        " where t.id = any($1::uuid[])",
        [waiting, queued],
    )
    by_id = {r["id"]: r for r in rows}
    assert by_id[queued]["expires_at"] is None
    assert by_id[waiting]["expires_at"] is not None
    days = by_id[waiting]["left_"].total_seconds() / 86400
    assert by_id[waiting]["offer_ttl_days"] - 0.01 < days <= by_id[waiting]["offer_ttl_days"]

"""M2 schema invariants: append-only events, idempotency keys, status vocabulary, realtime."""

import asyncpg
import pytest

pytestmark = pytest.mark.db


async def make_thread(factory):
    brand = await factory.brand()
    creator = await factory.creator()
    package_id = await factory.package(creator.id)
    brief_id = await factory.brief(brand)
    batch_id = await factory.batch(brief_id, brand)
    return await factory.thread(batch_id, brand, creator, package_id)


async def test_thread_events_reject_update(db_conn, factory):
    thread_id = await make_thread(factory)
    event_id = await factory.event(thread_id, "queued")

    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        await db_conn.execute(
            "update public.thread_events set actor = 'brand' where id = $1", event_id
        )


async def test_duplicate_event_external_id_rejected(factory):
    thread_id = await make_thread(factory)
    await factory.event(thread_id, "call_ended", external_id="conv-1")

    with pytest.raises(asyncpg.UniqueViolationError):
        await factory.event(thread_id, "call_ended", external_id="conv-1")


async def test_null_external_ids_never_collide(db_conn, factory):
    thread_id = await make_thread(factory)
    await factory.event(thread_id, "queued")
    await factory.event(thread_id, "queued")

    count = await db_conn.fetchval(
        "select count(*) from public.thread_events"
        " where thread_id = $1 and type = 'queued' and external_id is null",
        thread_id,
    )
    assert count == 2


async def test_unknown_status_rejected(db_conn, factory):
    thread_id = await make_thread(factory)

    with pytest.raises(asyncpg.CheckViolationError):
        await db_conn.execute("update public.threads set status = 'sent' where id = $1", thread_id)


async def test_thread_events_published_for_realtime(db_conn):
    found = await db_conn.fetchval(
        "select 1 from pg_publication_tables"
        " where pubname = 'supabase_realtime' and tablename = 'thread_events'"
    )
    assert found == 1


async def test_updated_at_touched_on_update(db_conn, factory):
    thread_id = await make_thread(factory)

    # The trigger must overwrite an explicit stale updated_at with now().
    await db_conn.execute(
        "update public.threads set status = 'drafting', updated_at = created_at - interval '1 hour'"
        " where id = $1",
        thread_id,
    )

    row = await db_conn.fetchrow(
        "select created_at, updated_at from public.threads where id = $1", thread_id
    )
    assert row["updated_at"] >= row["created_at"]

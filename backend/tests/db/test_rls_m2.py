"""Row-level security on the M2 tables: parties read through RLS, nobody else does."""

import asyncpg
import pytest

pytestmark = pytest.mark.db

M2_TABLES = ("briefs", "batches", "threads", "transcripts", "thread_events")


async def test_creator_cannot_read_briefs_or_batches(db_conn, as_user, factory):
    brand = await factory.brand()
    creator = await factory.creator()
    package_id = await factory.package(creator.id)
    brief_id = await factory.brief(brand)
    batch_id = await factory.batch(brief_id, brand)
    await factory.thread(batch_id, brand, creator, package_id)

    await as_user(db_conn, creator.profile_id)

    assert await db_conn.fetchval("select count(*) from public.briefs") == 0
    assert await db_conn.fetchval("select count(*) from public.batches") == 0


async def test_brand_reads_only_its_own_briefs(db_conn, as_user, factory):
    brand_a = await factory.brand()
    brand_b = await factory.brand()
    mine = await factory.brief(brand_a)
    theirs = await factory.brief(brand_b)
    my_batch = await factory.batch(mine, brand_a)
    await factory.batch(theirs, brand_b)

    await as_user(db_conn, brand_a.profile_id)

    assert {r[0] for r in await db_conn.fetch("select id from public.briefs")} == {mine}
    assert {r[0] for r in await db_conn.fetch("select id from public.batches")} == {my_batch}


async def test_thread_parties_read_threads_and_events(db_conn, as_user, factory):
    brand_a = await factory.brand()
    brand_b = await factory.brand()
    creator = await factory.creator()
    other_creator = await factory.creator()
    package_id = await factory.package(creator.id)
    brief_id = await factory.brief(brand_a)
    batch_id = await factory.batch(brief_id, brand_a)
    thread_id = await factory.thread(batch_id, brand_a, creator, package_id)
    await factory.event(thread_id, "email_drafted")
    await factory.event(thread_id, "email_sent")

    async def visible(profile_id):
        await db_conn.execute("reset role")
        await as_user(db_conn, profile_id)
        threads = await db_conn.fetchval("select count(*) from public.threads")
        events = await db_conn.fetchval("select count(*) from public.thread_events")
        return threads, events

    assert await visible(brand_a.profile_id) == (1, 2)
    assert await visible(brand_b.profile_id) == (0, 0)
    assert await visible(creator.profile_id) == (1, 2)
    assert await visible(other_creator.profile_id) == (0, 0)


async def test_creator_reads_call_transcript_but_not_intake(db_conn, as_user, factory):
    brand = await factory.brand()
    creator = await factory.creator()
    package_id = await factory.package(creator.id)
    brief_id = await factory.brief(brand)
    batch_id = await factory.batch(brief_id, brand)
    thread_id = await factory.thread(batch_id, brand, creator, package_id)
    call_id = await db_conn.fetchval(
        "insert into public.transcripts (thread_id, kind) values ($1, 'call') returning id",
        thread_id,
    )
    await db_conn.execute(
        "insert into public.transcripts (brief_id, kind) values ($1, 'intake')", brief_id
    )

    await as_user(db_conn, creator.profile_id)

    assert {r[0] for r in await db_conn.fetch("select id from public.transcripts")} == {call_id}


async def test_anon_reads_nothing(db_conn, factory):
    brand = await factory.brand()
    creator = await factory.creator()
    package_id = await factory.package(creator.id)
    brief_id = await factory.brief(brand)
    batch_id = await factory.batch(brief_id, brand)
    thread_id = await factory.thread(batch_id, brand, creator, package_id)
    await db_conn.execute(
        "insert into public.transcripts (thread_id, kind) values ($1, 'call')", thread_id
    )

    await db_conn.execute("set local role anon")

    for table in M2_TABLES:
        # anon holds no SELECT grant, so the read is refused (or, were it granted, RLS would
        # return nothing). Either way no row comes back. A savepoint keeps the refusal from
        # aborting the surrounding transaction for the next table.
        savepoint = db_conn.transaction()
        await savepoint.start()
        try:
            rows = await db_conn.fetch(f"select * from public.{table}")
        except asyncpg.InsufficientPrivilegeError:
            rows = []
        finally:
            await savepoint.rollback()
        assert rows == [], f"anon can read {table}"

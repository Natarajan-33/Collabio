"""The restart sweep requeues interrupted drafts and fails calls that were never placed."""

import json
from datetime import timedelta

import pytest

from app.modules.threads.repo import claim_queued
from app.workers.sweep import SweepResult, sweep_stuck

pytestmark = pytest.mark.db


async def thread_row(api_db, thread_id):
    async with api_db.acquire() as conn:
        return await conn.fetchrow(
            "select status, last_error from public.threads where id = $1", thread_id
        )


async def claim_all(api_db, batch_id) -> None:
    async with api_db.acquire() as conn:
        await claim_queued(conn, limit=10, batch_id=batch_id)


async def test_stuck_call_is_failed_not_redialed(api_db, launched_batch, fake_elevenlabs):
    arjun = launched_batch.threads["arjuntech"]
    await claim_all(api_db, launched_batch.batch_id)
    assert (await thread_row(api_db, arjun))["status"] == "calling"

    result = await sweep_stuck(api_db, stale_after=timedelta(0), batch_id=launched_batch.batch_id)

    reason = "Interrupted before the call was placed. Retry to call again."
    row = await thread_row(api_db, arjun)
    assert row["status"] == "failed"
    assert row["last_error"] == reason
    assert result.failed == 1
    async with api_db.acquire() as conn:
        events = await conn.fetch(
            "select payload from public.thread_events where thread_id = $1 and type = 'failed'",
            arjun,
        )
    assert [json.loads(e["payload"]) for e in events] == [{"reason": reason}]
    assert fake_elevenlabs.calls == []  # never re-dialed


async def test_stale_drafting_threads_are_requeued(api_db, launched_batch):
    threads = launched_batch.threads
    await claim_all(api_db, launched_batch.batch_id)

    result = await sweep_stuck(api_db, stale_after=timedelta(0), batch_id=launched_batch.batch_id)

    assert result == SweepResult(requeued=2, failed=1)
    for handle in ("priyareviews", "mayamakestech"):
        row = await thread_row(api_db, threads[handle])
        assert row["status"] == "queued"
        assert row["last_error"] == "Resumed after a restart"


async def test_calls_with_a_conversation_are_left_to_the_watcher(api_db, launched_batch):
    arjun = launched_batch.threads["arjuntech"]
    await claim_all(api_db, launched_batch.batch_id)
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.threads set call_conversation_id = $2 where id = $1",
            arjun,
            f"conv_{arjun}",
        )

    result = await sweep_stuck(api_db, stale_after=timedelta(0), batch_id=launched_batch.batch_id)

    assert result.failed == 0
    assert (await thread_row(api_db, arjun))["status"] == "calling"


async def test_sweep_leaves_fresh_threads_alone(api_db, launched_batch):
    await claim_all(api_db, launched_batch.batch_id)

    result = await sweep_stuck(api_db, batch_id=launched_batch.batch_id)

    assert result == SweepResult(requeued=0, failed=0)
    statuses = {
        handle: (await thread_row(api_db, thread_id))["status"]
        for handle, thread_id in launched_batch.threads.items()
    }
    assert statuses == {
        "priyareviews": "drafting",
        "mayamakestech": "drafting",
        "arjuntech": "calling",
    }

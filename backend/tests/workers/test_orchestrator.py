"""The orchestrator claims queued threads with skip-locked claims and isolates failures."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.modules.outreach.prompts import EmailDraft
from app.modules.outreach.service import send_outreach
from app.modules.threads.repo import claim_queued
from app.workers.orchestrator import Orchestrator
from app.workers.sweep import sweep_stuck

pytestmark = pytest.mark.db

GENERIC_FAILURE = "Something went wrong while processing. Retry to try again."


class Recorder:
    """A handler that records the thread ids it was given, and raises for `fail_for`."""

    def __init__(self, *, fail_for: set[UUID] | None = None) -> None:
        self.handled: list[UUID] = []
        self._fail_for = fail_for or set()

    async def __call__(self, thread_id: UUID) -> None:
        await asyncio.sleep(0)  # let the other handlers of the same pass interleave
        self.handled.append(thread_id)
        if thread_id in self._fail_for:
            raise RuntimeError("boom")


async def drain(orchestrator: Orchestrator) -> int:
    """Run `process_once` until nothing is left to claim; the number handled."""
    total = 0
    while count := await orchestrator.process_once():
        total += count
    return total


async def status_of(api_db, thread_id: UUID) -> str:
    async with api_db.acquire() as conn:
        return await conn.fetchval("select status from public.threads where id = $1", thread_id)


async def test_claim_moves_email_to_drafting_and_call_to_calling(api_db, launched_batch):
    async with api_db.acquire() as conn:
        claimed = await claim_queued(conn, limit=10, batch_id=launched_batch.batch_id)

    by_id = {c.id: c for c in claimed}
    threads = launched_batch.threads
    assert set(by_id) == set(threads.values())
    assert by_id[threads["arjuntech"]].channel_plan == "call"
    assert by_id[threads["arjuntech"]].status == "calling"
    for handle in ("priyareviews", "mayamakestech"):
        assert by_id[threads[handle]].channel_plan == "email"
        assert by_id[threads[handle]].status == "drafting"
    assert await status_of(api_db, threads["arjuntech"]) == "calling"
    assert await status_of(api_db, threads["priyareviews"]) == "drafting"


async def test_claim_respects_limit(api_db, launched_batch):
    async with api_db.acquire() as conn:
        some = await claim_queued(conn, limit=2, batch_id=launched_batch.batch_id)

    assert len(some) == 2
    statuses = [await status_of(api_db, t) for t in launched_batch.threads.values()]
    assert statuses.count("queued") == 1


async def test_launch_ten_with_one_failure(api_db, launched_ten):
    thread_ids = list(launched_ten.threads.values())
    assert len(thread_ids) == 10
    broken = thread_ids[3]
    email = Recorder(fail_for={broken})
    orchestrator = Orchestrator(
        api_db, {"email": email}, concurrency=5, batch_id=launched_ten.batch_id
    )

    assert await drain(orchestrator) == 10

    assert sorted(email.handled) == sorted(thread_ids)  # each thread handled exactly once
    async with api_db.acquire() as conn:
        row = await conn.fetchrow(
            "select status, last_error from public.threads where id = $1", broken
        )
        failed_events = await conn.fetch(
            "select payload from public.thread_events where thread_id = $1 and type = 'failed'",
            broken,
        )
        others = await conn.fetch(
            "select status from public.threads where batch_id = $1 and id <> $2",
            launched_ten.batch_id,
            broken,
        )
    assert row["status"] == "failed"
    assert row["last_error"] == GENERIC_FAILURE
    assert [json.loads(e["payload"]) for e in failed_events] == [{"reason": GENERIC_FAILURE}]
    assert {r["status"] for r in others} == {"drafting"}  # the recorder moves nothing


async def test_failures_are_isolated_per_thread(api_db, launched_batch):
    threads = launched_batch.threads
    email = Recorder(fail_for={threads["priyareviews"]})
    call = Recorder()
    orchestrator = Orchestrator(
        api_db, {"email": email, "call": call}, batch_id=launched_batch.batch_id
    )

    assert await drain(orchestrator) == 3

    assert sorted(email.handled) == sorted([threads["priyareviews"], threads["mayamakestech"]])
    assert call.handled == [threads["arjuntech"]]
    assert await status_of(api_db, threads["priyareviews"]) == "failed"
    assert await status_of(api_db, threads["mayamakestech"]) == "drafting"
    assert await status_of(api_db, threads["arjuntech"]) == "calling"


async def test_a_channel_without_a_handler_fails_only_that_thread(api_db, launched_batch):
    threads = launched_batch.threads
    email = Recorder()
    orchestrator = Orchestrator(api_db, {"email": email}, batch_id=launched_batch.batch_id)

    assert await drain(orchestrator) == 3

    assert await status_of(api_db, threads["arjuntech"]) == "failed"
    assert len(email.handled) == 2


async def test_two_orchestrators_never_share_a_thread(api_db, launched_batch):
    handled = Recorder()
    handlers = {"email": handled, "call": handled}
    o1 = Orchestrator(api_db, handlers, batch_id=launched_batch.batch_id)
    o2 = Orchestrator(api_db, handlers, batch_id=launched_batch.batch_id)

    counts = await asyncio.gather(o1.process_once(), o2.process_once())

    assert sum(counts) == 3
    assert sorted(handled.handled) == sorted(launched_batch.threads.values())


async def test_process_once_returns_zero_when_nothing_is_queued(api_db, launched_batch):
    orchestrator = Orchestrator(api_db, {}, batch_id=launched_batch.batch_id)
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.threads set status = 'failed' where batch_id = $1",
            launched_batch.batch_id,
        )

    assert await orchestrator.process_once() == 0


async def test_run_handles_threads_and_stops_on_cancel(api_db, launched_batch):
    handled = Recorder()
    orchestrator = Orchestrator(
        api_db,
        {"email": handled, "call": handled},
        poll_seconds=0.05,
        batch_id=launched_batch.batch_id,
    )
    task = asyncio.create_task(orchestrator.run())
    try:
        async with asyncio.timeout(15):
            while len(handled.handled) < 3:
                orchestrator.wake()
                await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert sorted(handled.handled) == sorted(launched_batch.threads.values())


async def test_restart_mid_launch_sends_each_email_once(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings, deliverable
):
    threads = launched_batch.threads
    priya = threads["priyareviews"]
    today = datetime.now(UTC).date()
    for _ in range(2):  # one reply for Priya's first attempt, one for Maya
        fake_gemini.queue_structured(
            EmailDraft(
                subject="Lumen Pods: three short videos?",
                opener="Your gadget reviews are a great fit for Lumen Pods.",
                ask_paragraph="We would love three short videos at $1,000 total.",
                rationale="Your audience cares about everyday audio gear.",
            )
        )

    async def email_handler(thread_id: UUID) -> None:
        await send_outreach(
            api_db,
            gemini=fake_gemini,
            email=lambda: fake_email,
            settings=m2_settings,
            thread_id=thread_id,
            today=today,
        )

    async with api_db.acquire() as conn:
        await claim_queued(conn, limit=10, batch_id=launched_batch.batch_id)
    fake_email.crash_after_send = True  # the process dies after Resend accepted the mail
    with pytest.raises(RuntimeError, match="crash"):
        await email_handler(priya)
    assert await status_of(api_db, priya) == "drafting"
    assert len(fake_email.sent) == 1
    fake_email.crash_after_send = False

    swept = await sweep_stuck(api_db, stale_after=timedelta(0), batch_id=launched_batch.batch_id)
    assert swept.requeued >= 1
    assert await status_of(api_db, priya) == "queued"

    orchestrator = Orchestrator(api_db, {"email": email_handler}, batch_id=launched_batch.batch_id)
    await orchestrator.process_once()

    assert await status_of(api_db, priya) == "awaiting_reply"
    # `deliverable` makes Maya's address deliverable too, so she is emailed (once) as well;
    # what matters is that Priya was emailed exactly once across the "restart".
    priya_sends = [key for _, key in fake_email.sent if key.startswith(f"thread:{priya}:")]
    assert priya_sends == [f"thread:{priya}:email:0"]
    assert len(fake_email.sent) == 2
    assert len(fake_gemini.calls) == 2  # Priya's draft was stored, then reused; Maya's is new
    async with api_db.acquire() as conn:
        drafts = await conn.fetchval(
            "select count(*) from public.thread_events"
            " where thread_id = $1 and type = 'email_drafted'",
            priya,
        )
    assert drafts == 1

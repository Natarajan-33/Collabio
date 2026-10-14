"""The expiry sweep moves lapsed `awaiting_reply` offers to `no_response`.

Every sweep is scoped to the test's batch so it never touches other rows of the shared database.
"""

import asyncio
from datetime import timedelta

import pytest

from app.workers import expiry
from app.workers.expiry import expire_offers, expiry_loop
from tests.api.helpers import events_of, force_status, send_held, thread_row

pytestmark = pytest.mark.db


async def lapse(api_db, thread_id, ago: timedelta = timedelta(hours=1)) -> None:
    """Make the thread's offer expire `ago`."""
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.threads set expires_at = now() - $2::interval where id = $1",
            thread_id,
            ago,
        )


@pytest.fixture
async def three_offers(launched_batch, api_db):
    """Priya's offer has lapsed, Maya's is still running and Arjun's thread is `countered`
    with an expiry left over from earlier: (batch id, priya, maya, arjun)."""
    threads = launched_batch.threads
    priya, maya, arjun = threads["priyareviews"], threads["mayamakestech"], threads["arjuntech"]
    for thread_id in (priya, maya, arjun):
        await send_held(api_db, thread_id)
    await force_status(api_db, arjun, "countered", event="counter_submitted", actor="creator")
    await lapse(api_db, priya)
    await lapse(api_db, arjun)  # the sweep must still look at the status
    return launched_batch.batch_id, priya, maya, arjun


async def test_expires_only_past_awaiting_reply(api_db, three_offers):
    batch_id, priya, maya, arjun = three_offers

    moved = await expire_offers(api_db, batch_id=batch_id)

    assert moved == 1
    row = await thread_row(api_db, priya)
    assert (row["status"], row["expires_at"]) == ("no_response", None)
    assert (await thread_row(api_db, maya))["status"] == "awaiting_reply"
    assert (await thread_row(api_db, arjun))["status"] == "countered"
    [expired] = await events_of(api_db, priya, "offer_expired")
    assert expired["actor"] == "system"
    assert await events_of(api_db, maya, "offer_expired") == []
    assert await events_of(api_db, arjun, "offer_expired") == []


async def test_expiry_idempotent(api_db, three_offers):
    batch_id, priya, *_ = three_offers

    first = await expire_offers(api_db, batch_id=batch_id)
    second = await expire_offers(api_db, batch_id=batch_id)

    assert (first, second) == (1, 0)
    assert len(await events_of(api_db, priya, "offer_expired")) == 1


async def test_expiry_respects_the_limit(api_db, three_offers):
    batch_id, priya, maya, _ = three_offers
    await lapse(api_db, maya, timedelta(hours=2))

    first = await expire_offers(api_db, limit=1, batch_id=batch_id)
    second = await expire_offers(api_db, limit=1, batch_id=batch_id)
    third = await expire_offers(api_db, limit=1, batch_id=batch_id)

    assert (first, second, third) == (1, 1, 0)
    assert (await thread_row(api_db, maya))["status"] == "no_response"  # the older expiry first
    assert (await thread_row(api_db, priya))["status"] == "no_response"


async def test_expiry_isolated_per_thread(api_db, three_offers, monkeypatch):
    batch_id, priya, maya, _ = three_offers
    await lapse(api_db, maya)
    real_due = expiry.due_offers

    async def due_then_change_one(*args, **kwargs):
        """After the sweep chose its threads, Priya's offer is countered by someone else."""
        due = await real_due(*args, **kwargs)
        assert priya in due and maya in due
        await force_status(api_db, priya, "countered", event="counter_submitted", actor="creator")
        return due

    monkeypatch.setattr(expiry, "due_offers", due_then_change_one)

    moved = await expire_offers(api_db, batch_id=batch_id)

    assert moved == 1
    assert (await thread_row(api_db, priya))["status"] == "countered"
    assert await events_of(api_db, priya, "offer_expired") == []
    assert (await thread_row(api_db, maya))["status"] == "no_response"


async def test_expiry_survives_a_failing_thread(api_db, three_offers, monkeypatch):
    batch_id, priya, maya, _ = three_offers
    await lapse(api_db, maya, timedelta(hours=2))
    real_apply = expiry.repo.apply_event

    async def fail_for_maya(conn, thread, **kwargs):
        if thread.id == maya:
            raise RuntimeError("boom")
        return await real_apply(conn, thread, **kwargs)

    monkeypatch.setattr(expiry.repo, "apply_event", fail_for_maya)

    moved = await expire_offers(api_db, batch_id=batch_id)

    assert moved == 1
    assert (await thread_row(api_db, maya))["status"] == "awaiting_reply"
    assert (await thread_row(api_db, priya))["status"] == "no_response"


async def test_loop_sweeps_repeatedly_and_survives_errors(monkeypatch):
    outcomes: list[int | Exception] = [0, RuntimeError("db down"), 2, 0]
    calls = 0
    done = asyncio.Event()

    async def fake_expire(db, **kwargs):
        nonlocal calls
        outcome = outcomes[calls] if calls < len(outcomes) else 0
        calls += 1
        if calls >= len(outcomes):
            done.set()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(expiry, "expire_offers", fake_expire)
    task = asyncio.create_task(expiry_loop(object(), interval_s=0.001))

    async with asyncio.timeout(5):
        await done.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls >= 4  # kept going after the exception

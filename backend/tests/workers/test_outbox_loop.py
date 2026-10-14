"""outbox_loop sends on a timer and survives a failing pass."""

import asyncio

import pytest

from app.workers import outbox
from app.workers.outbox import outbox_loop


async def test_loop_sends_repeatedly_and_survives_errors(monkeypatch):
    outcomes = [0, RuntimeError("db down"), 3, 0]
    calls: list[dict] = []
    done = asyncio.Event()

    async def fake_send_due(db, **kwargs):
        calls.append(kwargs)
        outcome = outcomes[len(calls) - 1] if len(calls) <= len(outcomes) else 0
        if len(calls) >= len(outcomes):
            done.set()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(outbox, "send_due", fake_send_due)
    task = asyncio.create_task(
        outbox_loop(object(), email=lambda: None, gemini=None, settings=object(), interval_s=0.001)
    )

    async with asyncio.timeout(5):
        await done.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(calls) >= 4  # kept going after the exception
    assert all(call["limit"] == 10 and call["gemini"] is None for call in calls)

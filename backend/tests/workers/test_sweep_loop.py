"""sweep_loop sweeps on a timer, wakes the orchestrator and survives a failing sweep."""

import asyncio
from datetime import timedelta

import pytest

from app.workers import sweep
from app.workers.sweep import SweepResult, sweep_loop

TICK = timedelta(milliseconds=1)


async def run_until(loop_task: asyncio.Task, done: asyncio.Event) -> None:
    async with asyncio.timeout(5):
        await done.wait()
    loop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop_task


async def test_sweeps_repeatedly_survives_errors_and_wakes_on_requeue(monkeypatch):
    outcomes = [SweepResult(0, 0), RuntimeError("db down"), SweepResult(2, 0), SweepResult(0, 1)]
    calls: list[dict] = []
    done = asyncio.Event()

    async def fake_sweep(db, **kwargs):
        calls.append(kwargs)
        outcome = outcomes[len(calls) - 1] if len(calls) <= len(outcomes) else SweepResult(0, 0)
        if len(calls) >= len(outcomes):
            done.set()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(sweep, "sweep_stuck", fake_sweep)
    woken: list[int] = []
    task = asyncio.create_task(
        sweep_loop(
            object(),
            every=TICK,
            stale_after=timedelta(minutes=2),
            on_requeued=lambda: woken.append(1),
        )
    )

    await run_until(task, done)

    assert len(calls) >= 4  # kept going after the exception in the second sweep
    assert all(c == {"stale_after": timedelta(minutes=2)} for c in calls)
    assert woken == [1]  # only the sweep that requeued woke the orchestrator


async def test_stops_on_cancel_without_sweeping_again(monkeypatch):
    calls: list[int] = []

    async def fake_sweep(db, **kwargs):
        calls.append(1)
        return SweepResult(0, 0)

    monkeypatch.setattr(sweep, "sweep_stuck", fake_sweep)
    task = asyncio.create_task(sweep_loop(object(), every=timedelta(hours=1)))
    await asyncio.sleep(0.01)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls == []  # the first periodic sweep is one `every` after the startup sweep


async def test_start_and_stop_workers_run_and_cancel_both_tasks(monkeypatch):
    from types import SimpleNamespace

    from app.config import Settings
    from app.workers import runtime

    started: list[str] = []
    cancelled: list[str] = []

    async def forever(name: str) -> None:
        started.append(name)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    async def no_sweep(db, **kwargs):
        return SweepResult(0, 0)

    monkeypatch.setattr(runtime, "sweep_stuck", no_sweep)
    monkeypatch.setattr(runtime, "sweep_loop", lambda db, **kw: forever("sweep"))
    monkeypatch.setattr(runtime.Orchestrator, "run", lambda self: forever("orchestrator"))
    app = SimpleNamespace(state=SimpleNamespace(db=object(), workers=None))

    await runtime.start_workers(app, Settings(_env_file=None, gemini_api_key=""))
    await asyncio.sleep(0)
    assert sorted(started) == ["orchestrator", "sweep"]

    await runtime.stop_workers(app)

    assert sorted(cancelled) == ["orchestrator", "sweep"]
    assert app.state.workers is None

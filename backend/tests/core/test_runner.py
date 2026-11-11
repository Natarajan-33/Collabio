"""Settlement dispatch: Render Workflows when enabled, in-process otherwise or on any error."""

from uuid import uuid4

from app.config import Settings
from app.modules.money import runner


def _settings(enabled: bool) -> Settings:
    return Settings(render_workflows_enabled=enabled, render_api_key="rnd_test")


async def test_runner_falls_back_in_process_on_trigger_error():
    settled, triggered = [], []

    async def settle(sid):
        settled.append(sid)

    async def trigger(settings, sid):
        triggered.append(sid)
        raise RuntimeError("Render API down")

    sid = uuid4()
    runner.start(settle, sid, _settings(True), trigger=trigger)
    await runner.wait_all()
    assert triggered == [sid]
    assert settled == [sid]


async def test_runner_uses_render_workflows_when_enabled():
    settled, triggered = [], []

    async def settle(sid):
        settled.append(sid)

    async def trigger(settings, sid):
        triggered.append(sid)

    sid = uuid4()
    runner.start(settle, sid, _settings(True), trigger=trigger)
    await runner.wait_all()
    assert (triggered, settled) == ([sid], [])


async def test_runner_runs_in_process_when_disabled():
    settled, triggered = [], []

    async def settle(sid):
        settled.append(sid)

    async def trigger(settings, sid):
        triggered.append(sid)

    sid = uuid4()
    runner.start(settle, sid, _settings(False), trigger=trigger)
    await runner.wait_all()
    assert (triggered, settled) == ([], [sid])

"""Render Workflows tasks delegate to the same MoneyService code as the API."""

from uuid import uuid4

import workflows.settlement as wf


def test_both_tasks_are_registered():
    assert {"settle_submission", "nightly_settlement"} <= set(wf.app._registry.get_task_names())


async def test_settle_submission_runs_the_service(monkeypatch):
    calls = []

    class FakeMoney:
        async def settle(self, sid):
            calls.append(("settle", sid))
            return "paid"

        async def nightly(self, redispatch):
            redispatch("stale-1")
            return {"payouts_synced": 2, "runs_retried": 1}

    async def fake_with_money(fn):
        return await fn(FakeMoney())

    monkeypatch.setattr(wf, "with_money", fake_with_money)
    settle = wf.app._registry.get_function("settle_submission")
    nightly = wf.app._registry.get_function("nightly_settlement")
    sid = uuid4()
    assert await settle(None, str(sid)) == "paid"
    assert await nightly(None) == {"payouts_synced": 2, "runs_retried": 1}
    assert calls == [("settle", sid), ("settle", "stale-1")]

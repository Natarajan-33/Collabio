"""The `launched_batch` fixture other tasks build on: three held threads and a private ceiling."""

import pytest

pytestmark = pytest.mark.db


async def test_launched_batch_holds_three_threads(api_db, launched_batch):
    assert set(launched_batch.threads) == {"priyareviews", "arjuntech", "mayamakestech"}
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select c.handle, t.channel_plan, t.status, t.next_action_at = 'infinity' as held"
            " from public.threads t join public.creators c on c.id = t.creator_id"
            " where t.batch_id = $1",
            launched_batch.batch_id,
        )
        ceiling = await conn.fetchval(
            "select budget_ceiling_cents from public.briefs where id = $1", launched_batch.brief_id
        )
    assert {r["handle"]: r["channel_plan"] for r in rows} == {
        "priyareviews": "email",
        "arjuntech": "call",
        "mayamakestech": "email",
    }
    assert {r["status"] for r in rows} == {"queued"}
    assert all(r["held"] for r in rows)
    assert ceiling == 123400

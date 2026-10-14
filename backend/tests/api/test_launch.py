"""POST /briefs/{id}/launch: a complete brief becomes a batch of queued threads.

Every launch that succeeds through the API uses only `fictional_ids` (reserved @example.com
addresses, email channel): a dev worker sharing the database could otherwise claim the threads
and send real email or place a real call.
"""

import asyncio
import json
from uuid import UUID

import pytest

from app.adapters.gemini import GeminiUnavailable
from tests.api.test_briefs import BASE, create, go_live, patch

pytestmark = pytest.mark.db

CEILING_CENTS = 123400
COMPLETE = {
    "deliverables_count": 3,
    "deliverables_format": "short_video",
    "budget_ceiling_cents": CEILING_CENTS,
    "ask_price_cents": 100000,
    "negotiation_ask": "Three short reviews for the Lumen Pods launch",
    "flexibility": ["timeline"],
}


async def complete_brief(client, cleanup: list[str], *creator_ids: UUID) -> str:
    brief = await create(client, cleanup, *creator_ids)
    r = await patch(client, brief["id"], go_live_by=go_live(30), **COMPLETE)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    return brief["id"]


def launch(client, brief_id: str, **body):
    return client.post(f"{BASE}/{brief_id}/launch", json=body)


async def test_launch_creates_batch_threads_and_queued_events(
    brand_client, api_db, brief_cleanup, fictional_ids
):
    brief_id = await complete_brief(brand_client, brief_cleanup, *fictional_ids)

    r = await launch(brand_client, brief_id, follow_up_policy="suggest")

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["thread_count"] == 2
    assert body["excluded"] == []
    batch_id = UUID(body["batch_id"])
    async with api_db.acquire() as conn:
        threads = await conn.fetch(
            "select id, creator_id, status, channel_plan, reply_token"
            " from public.threads where batch_id = $1",
            batch_id,
        )
        assert {t["creator_id"] for t in threads} == set(fictional_ids)
        assert {t["status"] for t in threads} == {"queued"}
        assert {t["channel_plan"] for t in threads} == {"email"}
        assert len({t["reply_token"] for t in threads}) == 2
        events = await conn.fetch(
            "select thread_id, type, actor from public.thread_events where batch_id = $1",
            batch_id,
        )
        assert sorted(e["thread_id"] for e in events) == sorted(t["id"] for t in threads)
        assert {(e["type"], e["actor"]) for e in events} == {("queued", "brand")}
        brief = await conn.fetchrow(
            "select status, approved_at from public.briefs where id = $1", UUID(brief_id)
        )
        assert brief["status"] == "launched"
        assert brief["approved_at"] is not None
        batch = await conn.fetchrow(
            "select follow_up_policy, brief_embedding is not null as embedded"
            " from public.batches where id = $1",
            batch_id,
        )
        assert batch["follow_up_policy"] == "suggest"
        assert batch["embedded"] is True


async def test_launch_incomplete_422_lists_missing(brand_client, brief_cleanup, fictional_ids):
    brief = await create(brand_client, brief_cleanup, *fictional_ids)

    r = await launch(brand_client, brief["id"])

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "brief_incomplete"
    assert "deliverables_count" in detail["missing"]
    assert detail["violations"] == []


async def test_launch_twice_409(brand_client, brief_cleanup, fictional_ids):
    brief_id = await complete_brief(brand_client, brief_cleanup, *fictional_ids)

    assert (await launch(brand_client, brief_id)).status_code == 201
    again = await launch(brand_client, brief_id)

    assert again.status_code == 409
    assert again.json()["detail"] == "brief_launched"


async def test_concurrent_launch_creates_one_batch(
    brand_client, api_db, brief_cleanup, fictional_ids
):
    brief_id = await complete_brief(brand_client, brief_cleanup, *fictional_ids)

    first, second = await asyncio.gather(
        launch(brand_client, brief_id), launch(brand_client, brief_id)
    )

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    async with api_db.acquire() as conn:
        count = await conn.fetchval(
            "select count(*) from public.batches where brief_id = $1", UUID(brief_id)
        )
    assert count == 1


async def test_call_without_opt_in_422(brand_client, brief_cleanup, seeded_ids):
    priya = seeded_ids["priya"]
    brief_id = await complete_brief(brand_client, brief_cleanup, priya)

    r = await launch(brand_client, brief_id, channels={str(priya): "call"})

    assert r.status_code == 422
    assert r.json()["detail"] == {
        "error": "channel_not_allowed",
        "creator_id": str(priya),
        "message": "No phone opt-in",
    }


async def test_launch_never_copies_ceiling(brand_client, api_db, brief_cleanup, fictional_ids):
    brief_id = await complete_brief(brand_client, brief_cleanup, *fictional_ids)

    r = await launch(brand_client, brief_id)

    assert r.status_code == 201, r.text
    batch_id = UUID(r.json()["batch_id"])
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select row_to_json(t)::text as j from public.threads t where batch_id = $1"
            " union all"
            " select row_to_json(e)::text from public.thread_events e where batch_id = $1",
            batch_id,
        )
    assert len(rows) == 4
    dump = json.dumps([row["j"] for row in rows])
    assert str(CEILING_CENTS) not in dump
    assert "1,234" not in dump


async def test_launch_survives_gemini_failure(
    brand_client, api_db, fake_gemini, brief_cleanup, fictional_ids
):
    fake_gemini.embed_failure = GeminiUnavailable("down")
    brief_id = await complete_brief(brand_client, brief_cleanup, *fictional_ids)

    r = await launch(brand_client, brief_id)

    assert r.status_code == 201, r.text
    async with api_db.acquire() as conn:
        embedding = await conn.fetchval(
            "select brief_embedding from public.batches where id = $1", UUID(r.json()["batch_id"])
        )
    assert embedding is None


async def test_creator_cannot_launch(creator_client):
    r = await creator_client.post(f"{BASE}/{UUID(int=1)}/launch", json={})

    assert r.status_code == 403


async def test_launch_rejects_unregistered_in_production(
    app, brand_client, api_db, brief_cleanup, fictional_ids
):
    from app.config import get_settings

    brief_id = await complete_brief(brand_client, brief_cleanup, *fictional_ids)
    settings = get_settings().model_copy(update={"demo_mode": False})
    app.dependency_overrides[get_settings] = lambda: settings

    r = await launch(brand_client, brief_id)

    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "creator_not_registered"
    assert set(detail["creator_ids"]) == {str(i) for i in fictional_ids}
    async with api_db.acquire() as conn:
        assert (
            await conn.fetchval(
                "select count(*) from public.batches where brief_id = $1", UUID(brief_id)
            )
            == 0
        )
        status = await conn.fetchval(
            "select status from public.briefs where id = $1", UUID(brief_id)
        )
    assert status == "ready"


async def test_launch_copies_hires_target(brand_client, api_db, brief_cleanup, fictional_ids):
    brief_id = await complete_brief(brand_client, brief_cleanup, *fictional_ids)
    r = await patch(brand_client, brief_id, hires_target=2)
    assert r.status_code == 200 and r.json()["hires_target"] == 2

    r = await launch(brand_client, brief_id)

    assert r.status_code == 201, r.text
    batch_id = UUID(r.json()["batch_id"])
    async with api_db.acquire() as conn:
        target = await conn.fetchval(
            "select hires_target from public.batches where id = $1", batch_id
        )
    assert target == 2
    view = await brand_client.get(f"/api/v1/batches/{batch_id}")
    assert view.status_code == 200, view.text
    assert view.json()["brief"]["hires_target"] == 2

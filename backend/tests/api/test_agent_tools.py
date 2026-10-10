"""The negotiation agent's server tools: `check_counter` and `log_offer`."""

import json
from uuid import UUID, uuid4

import pytest

from app.config import get_settings
from app.modules.threads.repo import claim_queued

pytestmark = pytest.mark.db

CHECK = "/api/v1/webhooks/elevenlabs/tools/check-counter"
LOG = "/api/v1/webhooks/elevenlabs/tools/log-offer"
HEADERS = {"X-Collabio-Tool-Secret": "tool-secret"}


async def claim_arjun(api_db, launched_batch) -> UUID:
    """Claim the batch (Arjun's call thread goes to `calling`) and return his thread id."""
    async with api_db.acquire() as conn:
        await claim_queued(conn, limit=10, batch_id=launched_batch.batch_id)
    return launched_batch.threads["arjuntech"]


def check_body(thread_id, price_usd=1300, videos=3) -> dict:
    return {"thread_id": str(thread_id), "price_usd": price_usd, "videos": videos}


def log_body(thread_id, **overrides) -> dict:
    body = {
        "thread_id": str(thread_id),
        "price_usd": 1300,
        "videos": 3,
        "stance": "counter",
        "speaker": "creator",
    }
    return body | overrides


async def event_count(api_db, thread_id) -> int:
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select count(*) from public.thread_events where thread_id = $1", thread_id
        )


async def concessions(api_db, thread_id) -> int:
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select concessions from public.threads where id = $1", thread_id
        )


async def test_tools_require_secret(client, m2_settings):
    body = {"thread_id": str(uuid4()), "price_usd": 1300, "videos": 3}
    for path in (CHECK, LOG):
        missing = await client.post(path, json=body)
        assert missing.status_code == 401
        assert missing.json()["detail"] == "invalid_tool_secret"
        wrong = await client.post(path, json=body, headers={"X-Collabio-Tool-Secret": "nope"})
        assert wrong.status_code == 401
        assert wrong.json()["detail"] == "invalid_tool_secret"


async def test_tools_unconfigured_503(app, client):
    unconfigured = get_settings().model_copy(update={"elevenlabs_tool_secret": ""})
    app.dependency_overrides[get_settings] = lambda: unconfigured
    body = {"thread_id": str(uuid4()), "price_usd": 1300, "videos": 3}
    for path in (CHECK, LOG):
        response = await client.post(path, json=body, headers=HEADERS)
        assert response.status_code == 503
        assert response.json()["detail"] == "tools_unconfigured"


async def test_over_suggests_midpoint_in_dollars(client, m2_settings, api_db, launched_batch):
    thread_id = await claim_arjun(api_db, launched_batch)
    response = await client.post(CHECK, json=check_body(thread_id), headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "verdict": "over",
        "suggested_counter_price_usd": 1117,
        "talking_point": "That's above what Lumen Audio can do. Offer $1,117 instead.",
    }
    assert await concessions(api_db, thread_id) == 1


async def test_second_over_moves_up(client, m2_settings, api_db, launched_batch):
    thread_id = await claim_arjun(api_db, launched_batch)
    first = await client.post(CHECK, json=check_body(thread_id), headers=HEADERS)
    assert first.json()["suggested_counter_price_usd"] == 1117
    second = await client.post(CHECK, json=check_body(thread_id), headers=HEADERS)
    assert second.status_code == 200, second.text
    assert second.json()["suggested_counter_price_usd"] == 1175
    assert await concessions(api_db, thread_id) == 2


async def test_within(client, m2_settings, api_db, launched_batch):
    thread_id = await claim_arjun(api_db, launched_batch)
    response = await client.post(CHECK, json=check_body(thread_id, price_usd=1200), headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "within"
    assert body["suggested_counter_price_usd"] is None
    assert await concessions(api_db, thread_id) == 0


async def test_unknown_thread_404(client, m2_settings, api_db):
    for path, body in ((CHECK, check_body(uuid4())), (LOG, log_body(uuid4()))):
        response = await client.post(path, json=body, headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["detail"] == "thread_not_found"


async def test_not_in_call_409(client, m2_settings, api_db, launched_batch):
    queued = launched_batch.threads["priyareviews"]
    for path, body in ((CHECK, check_body(queued)), (LOG, log_body(queued))):
        response = await client.post(path, json=body, headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["detail"] == "thread_not_in_call"
    assert await concessions(api_db, queued) == 0
    assert await event_count(api_db, queued) == 1  # only its `queued` event


async def test_check_counter_result_not_stored(client, m2_settings, api_db, launched_batch):
    thread_id = await claim_arjun(api_db, launched_batch)
    before = await event_count(api_db, thread_id)
    response = await client.post(CHECK, json=check_body(thread_id), headers=HEADERS)
    assert response.json()["suggested_counter_price_usd"] == 1117
    assert await event_count(api_db, thread_id) == before
    async with api_db.acquire() as conn:
        events = await conn.fetch(
            "select payload::text || coalesce(terms::text, '') as text"
            " from public.thread_events where thread_id = $1",
            thread_id,
        )
        thread = await conn.fetchrow(
            "select coalesce(latest_terms::text, '') || coalesce(last_error, '') as text"
            " from public.threads where id = $1",
            thread_id,
        )
    for text in [row["text"] for row in events] + [thread["text"]]:
        for needle in ("1117", "111700", "1234", "123400"):
            assert needle not in text


async def test_log_offer_appends_event_and_latest_terms(
    client, m2_settings, api_db, launched_batch
):
    thread_id = await claim_arjun(api_db, launched_batch)
    response = await client.post(
        LOG,
        json=log_body(
            thread_id, go_live_by="2026-11-20", conditions="usage rights, no exclusivity,"
        ),
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"logged": True}
    async with api_db.acquire() as conn:
        event = await conn.fetchrow(
            "select actor, payload, terms from public.thread_events"
            " where thread_id = $1 and type = 'call_offer_logged'",
            thread_id,
        )
        thread = await conn.fetchrow(
            "select status, latest_terms, latest_terms_source from public.threads where id = $1",
            thread_id,
        )
    assert event["actor"] == "creator"
    assert json.loads(event["payload"]) == {"speaker": "creator"}
    terms = json.loads(event["terms"])
    assert terms["price_cents"] == 130000
    assert terms["videos"] == 3
    assert terms["source"] == "call"
    assert terms["stance"] == "counter"
    assert terms["go_live_by"] == "2026-11-20"
    assert terms["conditions"] == ["usage rights", "no exclusivity"]
    assert json.loads(thread["latest_terms"])["price_cents"] == 130000
    assert thread["latest_terms_source"] == "creator"
    assert thread["status"] == "calling"


async def test_agent_offer_sets_brand_source(client, m2_settings, api_db, launched_batch):
    thread_id = await claim_arjun(api_db, launched_batch)
    response = await client.post(
        LOG,
        json=log_body(thread_id, price_usd=1117, stance="offer", speaker="agent"),
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    async with api_db.acquire() as conn:
        actor = await conn.fetchval(
            "select actor from public.thread_events"
            " where thread_id = $1 and type = 'call_offer_logged'",
            thread_id,
        )
        source = await conn.fetchval(
            "select latest_terms_source from public.threads where id = $1", thread_id
        )
    assert actor == "brand_agent"
    assert source == "brand"


async def test_log_offer_without_price_or_videos_keeps_latest_terms(
    client, m2_settings, api_db, launched_batch
):
    thread_id = await claim_arjun(api_db, launched_batch)
    body = {"thread_id": str(thread_id), "stance": "question", "speaker": "creator"}
    response = await client.post(LOG, json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    async with api_db.acquire() as conn:
        latest = await conn.fetchval(
            "select latest_terms from public.threads where id = $1", thread_id
        )
        logged = await conn.fetchval(
            "select count(*) from public.thread_events"
            " where thread_id = $1 and type = 'call_offer_logged'",
            thread_id,
        )
    assert latest is None
    assert logged == 1


async def test_log_offer_ignores_unparseable_date(client, m2_settings, api_db, launched_batch):
    thread_id = await claim_arjun(api_db, launched_batch)
    response = await client.post(
        LOG, json=log_body(thread_id, go_live_by="next friday"), headers=HEADERS
    )
    assert response.status_code == 200, response.text
    async with api_db.acquire() as conn:
        terms = await conn.fetchval(
            "select terms from public.thread_events"
            " where thread_id = $1 and type = 'call_offer_logged'",
            thread_id,
        )
    assert json.loads(terms)["go_live_by"] is None

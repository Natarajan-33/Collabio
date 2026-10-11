"""POST /voice/try-call: sample negotiation dial-out without storing the number."""

import json

import pytest

pytestmark = pytest.mark.db

TRY = "/api/v1/voice/try-call"


@pytest.fixture(autouse=True)
async def clear_call_conversation_ids(api_db):
    async with api_db.acquire() as conn:
        await conn.execute("update public.threads set call_conversation_id = null")


async def test_try_call_places_and_does_not_store_phone(
    brand_client, api_db, fake_elevenlabs, m2_settings
):
    phone = "+15559876543"
    r = await brand_client.post(TRY, json={"phone": phone, "scenario": "standard"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "calling"
    assert "creator" in body["message"].lower()

    assert len(fake_elevenlabs.calls) == 1
    assert fake_elevenlabs.calls[0]["to_number"] == phone

    async with api_db.acquire() as conn:
        stored = await conn.fetchval(
            "select count(*) from public.creators where phone = $1", phone
        )
        assert stored == 0
        thread_id = await conn.fetchval(
            "select thread_id from public.thread_events"
            " where type = 'call_placed' order by id desc limit 1"
        )
        (queued,) = await conn.fetch(
            "select payload from public.thread_events"
            " where thread_id = $1 and type = 'queued'",
            thread_id,
        )
        payload = json.loads(queued["payload"])
        assert payload["voice_try"] is True


async def test_try_call_rate_limited(brand_client, fake_elevenlabs, m2_settings, monkeypatch):
    from app.modules.voice import try_call as mod

    monkeypatch.setattr(mod, "MAX_TRY_CALLS_PER_USER_PER_DAY", 0)
    r = await brand_client.post(TRY, json={"phone": "+15551110000", "scenario": "rush"})
    assert r.status_code == 429
    assert fake_elevenlabs.calls == []


async def test_try_call_invalid_phone(brand_client, fake_elevenlabs):
    r = await brand_client.post(TRY, json={"phone": "not-a-phone", "scenario": "standard"})
    assert r.status_code == 422
    assert fake_elevenlabs.calls == []


async def test_creator_gets_creator_message(creator_client, fake_elevenlabs, m2_settings):
    r = await creator_client.post(TRY, json={"phone": "+15552223333", "scenario": "single_video"})
    assert r.status_code == 200, r.text
    assert "sample brand" in r.json()["message"].lower()

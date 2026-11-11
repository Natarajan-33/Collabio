"""Hackathon mode over HTTP: calls refused, usage caps enforced."""

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.modules.money import usage

pytestmark = pytest.mark.db


@pytest.fixture
def hackathon_settings(app):
    settings = get_settings().model_copy(update={"hackathon_mode": True})
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


async def test_try_call_forbidden_in_hackathon_mode(
    brand_client, fake_elevenlabs, hackathon_settings
):
    r = await brand_client.post(
        "/api/v1/voice/try-call", json={"phone": "+15551110000", "scenario": "standard"}
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "disabled_in_demo"
    assert fake_elevenlabs.calls == []


async def test_consume_raises_429_after_cap(api_db, auth_user, hackathon_settings):
    try:
        for _ in range(30):
            await usage.consume(api_db, auth_user, "settlement", hackathon_settings)
        with pytest.raises(HTTPException) as exc:
            await usage.consume(api_db, auth_user, "settlement", hackathon_settings)
        assert exc.value.status_code == 429
        assert exc.value.detail == "demo_cap"
    finally:
        async with api_db.acquire() as conn:
            await conn.execute("delete from public.usage_counters where user_id = $1", auth_user)


async def test_consume_is_noop_outside_hackathon_mode(api_db, auth_user):
    settings = get_settings().model_copy(update={"hackathon_mode": False})
    for _ in range(31):
        await usage.consume(api_db, auth_user, "settlement", settings)
    async with api_db.acquire() as conn:
        assert (
            await conn.fetchval(
                "select count(*) from public.usage_counters where user_id = $1", auth_user
            )
            == 0
        )

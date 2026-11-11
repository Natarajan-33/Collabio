"""Flat money tables for the brand's AG Studio dashboard, and the agent message cap."""

import pytest

from app.config import get_settings

pytestmark = pytest.mark.db


async def test_dashboard_tables_for_brand(brand_client, funded):
    deal_id, _ = funded
    r = await brand_client.get("/api/v1/money/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"deals", "milestones", "payouts", "money_events", "creators"}
    deal = next(d for d in body["deals"] if d["id"] == deal_id)
    assert deal["funded"] == 1200.0  # dollars, for currency widgets
    assert deal["status"] == "funded"
    assert {"title", "creator_id", "created_at", "videos"} <= set(deal)
    assert all(m["deal_id"] for m in body["milestones"])


async def test_dashboard_is_brand_only(creator_client):
    assert (await creator_client.get("/api/v1/money/dashboard")).status_code == 403


async def test_agent_usage_cap(brand_client, api_db, app):
    settings = get_settings().model_copy(update={"hackathon_mode": True})
    app.dependency_overrides[get_settings] = lambda: settings
    async with api_db.acquire() as conn:
        await conn.execute("delete from public.usage_counters where kind = 'agent_message'")
    assert (await brand_client.post("/api/v1/money/agent-usage")).status_code == 204
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.usage_counters set count = 40 where kind = 'agent_message'"
        )
    assert (await brand_client.post("/api/v1/money/agent-usage")).status_code == 429

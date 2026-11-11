"""Bonus terms and the auto-approve limit: brand-owner only, editable until funded."""

import pytest

from tests.fakes import claude_text

pytestmark = pytest.mark.db

TERMS_REPLY = {
    "question": "",
    "has_cpm": True,
    "cpm_rate_per_1k_dollars": 2,
    "cpm_starts_after_views": 200000,
    "cpm_cap_dollars": 500,
    "tiers": [{"views": 1000000, "bonus_dollars": 300}],
}
TERMS_JSON = {
    "cpm": {"rate_cents_per_1k": 200, "starts_after_views": 200000, "cap_cents": 50000},
    "tiers": [{"views": 1000000, "bonus_cents": 30000}],
}


async def test_preview_examples_and_funding_total(brand_client, booked, fake_claude):
    _, deal_id = booked
    fake_claude.script.append(claude_text(TERMS_REPLY))
    r = await brand_client.post(
        f"/api/v1/deals/{deal_id}/bonus-terms/preview", json={"text": "$2 per 1K after 200K"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["terms"] == TERMS_JSON
    assert body["max_bonus_per_video_cents"] == 80000
    assert body["funding_total_cents"] == 120000 + 3 * 80000
    assert body["examples"] == [
        {"views": 100000, "bonus_cents": 0},
        {"views": 500000, "bonus_cents": 50000},
        {"views": 1000000, "bonus_cents": 80000},
    ]


async def test_preview_question_is_422(brand_client, booked, fake_claude):
    _, deal_id = booked
    fake_claude.script.append(claude_text({**TERMS_REPLY, "question": "Per video?"}))
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/bonus-terms/preview", json={"text": "x"})
    assert r.status_code == 422
    assert r.json()["detail"] == {"code": "terms_question", "question": "Per video?"}


async def test_put_bonus_terms_then_409_after_funding(brand_client, booked, api_db):
    _, deal_id = booked
    url = f"/api/v1/deals/{deal_id}/bonus-terms"
    r = await brand_client.put(url, json={"source_text": "x", "terms": TERMS_JSON})
    assert r.status_code == 200, r.text
    async with api_db.acquire() as conn:
        stored = await conn.fetchval(
            "select max_bonus_per_video_cents from public.deal_bonus_terms where deal_id = $1",
            deal_id,
        )
        assert stored == 80000
        await conn.execute("update public.deals set status = 'funded' where id = $1", deal_id)
    r = await brand_client.put(url, json={"source_text": "x", "terms": TERMS_JSON})
    assert r.status_code == 409
    assert r.json()["detail"] == "already_funded"


async def test_put_invalid_terms_422(brand_client, booked):
    _, deal_id = booked
    bad = {
        "cpm": None,
        "tiers": [{"views": 900, "bonus_cents": 1}, {"views": 100, "bonus_cents": 1}],
    }
    r = await brand_client.put(
        f"/api/v1/deals/{deal_id}/bonus-terms", json={"source_text": "", "terms": bad}
    )
    assert r.status_code == 422


async def test_other_brand_gets_404_and_creator_403(new_brand_client, creator_client, booked):
    _, deal_id = booked
    url = f"/api/v1/deals/{deal_id}/bonus-terms"
    body = {"source_text": "", "terms": TERMS_JSON}
    assert (await new_brand_client.put(url, json=body)).status_code == 404
    assert (await creator_client.put(url, json=body)).status_code == 403


async def test_limit_out_of_range_422_and_saved(brand_client, api_db):
    url = "/api/v1/me/brand/auto-approve-limit"
    assert (await brand_client.put(url, json={"cents": 1_000_001})).status_code == 422
    r = await brand_client.put(url, json={"cents": 50_000})
    assert r.status_code == 200, r.text
    assert r.json() == {"cents": 50_000}
    await brand_client.put(url, json={"cents": 30_000})  # leave the demo brand at the default

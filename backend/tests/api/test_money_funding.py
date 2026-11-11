"""Funding a booked deal through PayPal Checkout, and the money view both sides read."""

import asyncio

import pytest

pytestmark = pytest.mark.db

TERMS_JSON = {
    "cpm": {"rate_cents_per_1k": 200, "starts_after_views": 200000, "cap_cents": 50000},
    "tiers": [{"views": 1000000, "bonus_cents": 30000}],
}


async def order_and_capture(client, deal_id):
    r = await client.post(f"/api/v1/deals/{deal_id}/funding/order")
    assert r.status_code == 200, r.text
    order_id = r.json()["order_id"]
    return order_id, await client.post(
        f"/api/v1/deals/{deal_id}/funding/capture", json={"order_id": order_id}
    )


async def ledger_kinds(api_db, deal_id):
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select kind, amount_cents from public.money_events where deal_id = $1 order by id",
            deal_id,
        )
    return [(r["kind"], r["amount_cents"]) for r in rows]


async def test_order_then_capture_marks_funded_and_ledger(
    brand_client, booked, fake_paypal, api_db
):
    _, deal_id = booked
    await brand_client.put(
        f"/api/v1/deals/{deal_id}/bonus-terms", json={"source_text": "", "terms": TERMS_JSON}
    )
    order_id, r = await order_and_capture(brand_client, deal_id)
    assert r.status_code == 200, r.text
    view = r.json()
    assert fake_paypal.orders[order_id] == {"amount_cents": 360000, "custom_id": deal_id}
    assert view["deal_status"] == "funded"
    assert view["funding"]["status"] == "captured"
    assert view["funding"]["amount_cents"] == 360000
    assert view["available_cents"] == 360000
    assert view["funding_total_cents"] == 360000
    assert [m["status"] for m in view["milestones"]] == ["funded", "funded", "funded"]
    assert view["can_close"] is False
    assert await ledger_kinds(api_db, deal_id) == [("funded", 360000)]


async def test_double_capture_is_idempotent(brand_client, booked, fake_paypal, api_db):
    _, deal_id = booked
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    order_id = r.json()["order_id"]
    url = f"/api/v1/deals/{deal_id}/funding/capture"
    first, second = await asyncio.gather(
        brand_client.post(url, json={"order_id": order_id}),
        brand_client.post(url, json={"order_id": order_id}),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert fake_paypal.captures == 1
    assert await ledger_kinds(api_db, deal_id) == [("funded", 120000)]


async def test_capture_amount_mismatch_409(brand_client, booked, fake_paypal, api_db):
    _, deal_id = booked
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    order_id = r.json()["order_id"]
    fake_paypal.orders[order_id]["amount_cents"] = 1
    r = await brand_client.post(
        f"/api/v1/deals/{deal_id}/funding/capture", json={"order_id": order_id}
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "funding_mismatch"
    assert await ledger_kinds(api_db, deal_id) == []


async def test_order_for_funded_deal_409(brand_client, booked, fake_paypal):
    _, deal_id = booked
    await order_and_capture(brand_client, deal_id)
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    assert r.status_code == 409
    assert r.json()["detail"] == "already_funded"


async def test_creator_money_view_hides_limit(brand_client, creator_client, booked, fake_paypal):
    _, deal_id = booked
    await order_and_capture(brand_client, deal_id)
    brand_view = (await brand_client.get(f"/api/v1/deals/{deal_id}/money")).json()
    assert brand_view["auto_approve_limit_cents"] == 30000
    r = await creator_client.get(f"/api/v1/deals/{deal_id}/money")
    assert r.status_code == 200, r.text
    assert r.json()["auto_approve_limit_cents"] is None
    assert r.json()["funding"]["status"] == "captured"


async def test_other_brand_cannot_fund_or_read(new_brand_client, booked, fake_paypal):
    _, deal_id = booked
    assert (
        await new_brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    ).status_code == 404
    assert (await new_brand_client.get(f"/api/v1/deals/{deal_id}/money")).status_code == 404

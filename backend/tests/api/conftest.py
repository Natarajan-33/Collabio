"""Fixtures shared by the deal-loop API tests (board actions, award, deals)."""

import pytest

from tests.api.helpers import send_held

OFFERS = "/api/v1/offers"


@pytest.fixture
async def offer(launched_batch, api_db):
    """Priya's sent offer: (thread id, id of the `email_sent` event)."""
    thread_id = launched_batch.threads["priyareviews"]
    return thread_id, await send_held(api_db, thread_id)


@pytest.fixture
async def countered(offer, creator_client):
    """Priya's offer after she countered 3 videos at $1,200 (no go-live date): (thread id, the
    id of her counter's event, which is the thread's newest terms event)."""
    thread_id, sent_id = offer
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter",
        json={
            "terms": {"videos": 3, "price_cents": 120000},
            "based_on_event_id": sent_id,
            "confirm_below_floor": True,  # Priya's own floor may sit above $1,200
        },
    )
    assert r.status_code == 200, r.text
    return thread_id, r.json()["terms_event_id"]


@pytest.fixture
async def booked(brand_client, countered):
    """Priya's awarded offer: (thread id, deal id)."""
    thread_id, counter_id = countered
    preview = (await brand_client.post(f"/api/v1/threads/{thread_id}/award/preview")).json()
    r = await brand_client.post(
        f"/api/v1/threads/{thread_id}/award",
        json={"milestones": preview["milestones"], "based_on_event_id": counter_id},
    )
    assert r.status_code == 200, r.text
    return thread_id, r.json()["id"]


@pytest.fixture
def fake_paypal(app):
    from app.api.deps import get_paypal
    from tests.fakes import FakePayPal

    paypal = FakePayPal()
    app.dependency_overrides[get_paypal] = lambda: paypal
    return paypal


@pytest.fixture
def fake_claude(app):
    from app.api.deps import get_claude
    from tests.fakes import FakeClaude

    claude = FakeClaude()
    app.dependency_overrides[get_claude] = lambda: claude
    return claude


@pytest.fixture
def fake_storage(app):
    from app.api.deps import get_storage
    from tests.fakes import FakeStorage

    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    return storage


@pytest.fixture
async def funded(brand_client, booked, fake_paypal, api_db):
    """Priya's booked deal funded through (fake) PayPal: (deal id, [milestone ids])."""
    _, deal_id = booked
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    order_id = r.json()["order_id"]
    r = await brand_client.post(
        f"/api/v1/deals/{deal_id}/funding/capture", json={"order_id": order_id}
    )
    assert r.status_code == 200, r.text
    async with api_db.acquire() as conn:
        # The local .env may run hackathon mode: start every money test with fresh caps.
        await conn.execute("delete from public.usage_counters")
        await conn.execute(
            "update public.creators set payout_email = 'priya-sandbox@example.com'"
            " where id = (select creator_id from public.deals where id = $1)",
            deal_id,
        )
    return deal_id, [m["id"] for m in r.json()["milestones"]]

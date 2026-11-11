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

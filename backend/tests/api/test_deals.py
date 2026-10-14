"""Deal views: each side lists and reads its own deals, and contact emails cross sides only here.

Priya's countered offer is awarded through the API (the `booked` fixture); she and Lumen Audio
are the two parties.
"""

import pytest

from tests.api.helpers import events_of, outbox_of

pytestmark = pytest.mark.db

THREADS = "/api/v1/threads"
BATCHES = "/api/v1/batches"
OFFERS = "/api/v1/offers"
DEALS = "/api/v1/deals"


@pytest.fixture
async def booked(brand_client, countered):
    """Priya's awarded offer: (thread id, deal id)."""
    thread_id, counter_id = countered
    preview = (await brand_client.post(f"{THREADS}/{thread_id}/award/preview")).json()
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/award",
        json={"milestones": preview["milestones"], "based_on_event_id": counter_id},
    )
    assert r.status_code == 200, r.text
    return thread_id, r.json()["id"]


@pytest.fixture
async def contacts(booked, launched_batch, api_db):
    """(Priya's email, the brief's contact email)."""
    thread_id, _ = booked
    async with api_db.acquire() as conn:
        creator = await conn.fetchval(
            "select c.email from public.creators c join public.threads t on t.creator_id = c.id"
            " where t.id = $1",
            thread_id,
        )
        brand = await conn.fetchval(
            "select contact_email from public.briefs where id = $1", launched_batch.brief_id
        )
    assert creator and brand
    return creator, brand


async def test_brand_lists_and_reads_deal(brand_client, booked, contacts, launched_batch):
    thread_id, deal_id = booked
    creator_email, contact_email = contacts
    listing = await brand_client.get(DEALS)
    assert listing.status_code == 200, listing.text
    item = next(d for d in listing.json() if d["id"] == deal_id)
    assert item["thread_id"] == str(thread_id)
    assert item["counterpart_name"]
    assert item["product_name"]
    assert (item["videos"], item["price_cents"], item["status"]) == (3, 120000, "booked")
    assert item["go_live_by"] and item["created_at"]
    assert creator_email not in listing.text  # contact details are in the deal view only

    r = await brand_client.get(f"{DEALS}/{deal_id}")
    assert r.status_code == 200, r.text
    deal = r.json()
    assert deal["id"] == deal_id
    assert deal["batch_id"] == str(launched_batch.batch_id)
    assert deal["status"] == "booked"
    assert deal["creator_handle"] == "priyareviews"
    assert deal["terms"]["videos"] == 3
    assert [m["amount_cents"] for m in deal["milestones"]] == [40000] * 3
    assert [m["seq"] for m in deal["milestones"]] == [1, 2, 3]
    assert deal["creator"]["email"] == creator_email
    assert deal["brand"]["email"] == contact_email
    assert "phone" not in r.text


async def test_creator_lists_and_reads_deal(creator_client, booked, contacts):
    thread_id, deal_id = booked
    creator_email, contact_email = contacts
    listing = await creator_client.get(DEALS)
    assert listing.status_code == 200, listing.text
    item = next(d for d in listing.json() if d["id"] == deal_id)
    assert item["counterpart_name"] == "Lumen Audio"
    assert contact_email not in listing.text

    r = await creator_client.get(f"{DEALS}/{deal_id}")
    assert r.status_code == 200, r.text
    deal = r.json()
    assert deal["thread_id"] == str(thread_id)
    assert deal["brand"]["email"] == contact_email  # revealed on booking
    assert deal["brand"]["name"] == "Lumen Audio"
    assert deal["creator"]["email"] == creator_email
    assert len(deal["milestones"]) == 3


async def test_other_parties_404(new_brand_client, booked):
    _, deal_id = booked
    r = await new_brand_client.get(f"{DEALS}/{deal_id}")
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "not_found"
    assert (await new_brand_client.get(DEALS)).json() == []


async def test_other_creator_404(new_creator_client, booked):
    _, deal_id = booked
    r = await new_creator_client.get(f"{DEALS}/{deal_id}")
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "not_found"
    assert (await new_creator_client.get(DEALS)).json() == []


async def test_unknown_deal_404(brand_client, creator_client):
    missing = "00000000-0000-0000-0000-000000000000"
    for client in (brand_client, creator_client):
        r = await client.get(f"{DEALS}/{missing}")
        assert r.status_code == 404
        assert r.json()["detail"] == "not_found"


async def test_deals_need_login(client):
    assert (await client.get(DEALS)).status_code == 401


async def test_contact_only_in_deal_view(
    brand_client, creator_client, booked, contacts, launched_batch, api_db
):
    thread_id, deal_id = booked
    creator_email, contact_email = contacts

    brand_side = [
        (await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")).text,
        (await brand_client.get(BATCHES)).text,
        (await brand_client.get(f"{THREADS}/{thread_id}")).text,
        (await brand_client.get(DEALS)).text,
    ]
    for body in brand_side:
        assert creator_email not in body
    creator_side = [
        (await creator_client.get(f"{OFFERS}/{thread_id}")).text,
        (await creator_client.get(OFFERS)).text,
        (await creator_client.get(f"{OFFERS}/counts")).text,
        (await creator_client.get(DEALS)).text,
    ]
    for body in creator_side:
        assert contact_email not in body

    # Nor do they ride along in events or notifications.
    stored = str(
        [(e["payload"], e["terms"]) for e in await events_of(api_db, thread_id)]
        + [o["payload"] for o in await outbox_of(api_db, thread_id)]
    )
    assert creator_email not in stored and contact_email not in stored

    # The deal view is where they appear.
    assert creator_email in (await brand_client.get(f"{DEALS}/{deal_id}")).text
    assert contact_email in (await creator_client.get(f"{DEALS}/{deal_id}")).text

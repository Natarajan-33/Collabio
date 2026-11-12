"""The creator's offers: list, counts and the offer desk.

Priya's thread of the held `launched_batch` is moved to `awaiting_reply` with `send_held`, which
sends nothing. The brief's private ceiling is 123400 and its contact email never reaches a
creator before a deal.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.threads import repo
from app.schemas.negotiation import NegotiationTerms
from tests.api.helpers import record_brand_counter, send_held

pytestmark = pytest.mark.db

OFFERS = "/api/v1/offers"


async def brief_contact_email(api_db, brief_id) -> str | None:
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select contact_email from public.briefs where id = $1", brief_id
        )


async def priya_floor(api_db, thread_id):
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select f.floor_price_cents from public.threads t"
            " left join public.package_floors f on f.package_id = t.package_id"
            " where t.id = $1",
            thread_id,
        )


def _ours(offers, launched_batch):
    """Only this test's threads: the shared demo creator also holds the money demo's deals."""
    ids = {str(t) for t in launched_batch.threads.values()}
    return [o for o in offers if o["thread_id"] in ids]


async def test_unsent_offers_hidden(creator_client, launched_batch):
    r = await creator_client.get(OFFERS)
    assert r.status_code == 200, r.text
    assert _ours(r.json(), launched_batch) == []


async def test_sent_offer_listed_for_priya(creator_client, launched_batch, api_db):
    thread_id = launched_batch.threads["priyareviews"]
    await send_held(api_db, thread_id)
    r = await creator_client.get(OFFERS)
    assert r.status_code == 200, r.text
    (offer,) = _ours(r.json(), launched_batch)
    assert offer["thread_id"] == str(thread_id)
    assert offer["brand"]["name"] == "Lumen Audio"
    assert offer["status"] == "awaiting_reply"
    assert offer["waiting_on"] == "creator"
    assert offer["total_value_cents"] == 100000
    assert offer["package"]["id"]
    assert offer["delta_headline"]
    expires = datetime.fromisoformat(offer["expires_at"])
    assert abs(expires - (datetime.now(UTC) + timedelta(days=7))) < timedelta(minutes=5)


async def test_tabs_and_counts(creator_client, launched_batch, api_db):
    before = (await creator_client.get(f"{OFFERS}/counts")).json()
    await send_held(api_db, launched_batch.threads["priyareviews"])
    counts = await creator_client.get(f"{OFFERS}/counts")
    assert counts.status_code == 200, counts.text
    delta = {k: counts.json()[k] - before[k] for k in before}
    assert delta == {"needs_you": 1, "waiting": 0, "booked": 0, "closed": 0}

    needs_you = await creator_client.get(OFFERS, params={"tab": "needs_you"})
    assert len(_ours(needs_you.json(), launched_batch)) == 1
    for tab in ("waiting", "booked", "closed"):
        r = await creator_client.get(OFFERS, params={"tab": tab})
        assert r.status_code == 200
        assert _ours(r.json(), launched_batch) == []


async def test_desk_columns(creator_client, launched_batch, api_db):
    thread_id = launched_batch.threads["priyareviews"]
    sent_id = await send_held(api_db, thread_id)
    r = await creator_client.get(f"{OFFERS}/{thread_id}")
    assert r.status_code == 200, r.text
    desk = r.json()
    assert desk["their_ask"]["videos"] == 3
    assert desk["their_ask"]["price_cents"] == 100000
    assert desk["their_ask"]["per_video_cents"] == 33333
    assert desk["my_package"]["videos"] == desk["package"]["volume_count"]
    assert desk["my_package"]["price_cents"] == desk["package"]["base_price_cents"]
    assert desk["latest"] is None
    assert desk["latest_source"] is None
    assert desk["changed"] == []
    assert desk["allowed_actions"] == ["counter", "accept", "decline"]
    assert desk["terms_event_id"] == sent_id
    assert desk["floor_price_cents"] == await priya_floor(api_db, thread_id)
    assert desk["brand"]["name"] == "Lumen Audio"
    assert desk["waiting_on"] == "creator"
    assert desk["deal_id"] is None
    assert [e["type"] for e in desk["events"]][-1] == "email_sent"
    assert desk["delta"]["ask_videos"] == 3


async def test_desk_shows_brand_note_and_changed(creator_client, launched_batch, api_db):
    thread_id = launched_batch.threads["priyareviews"]
    await send_held(api_db, thread_id)
    counter_id = await record_brand_counter(api_db, thread_id, 110000, note="Can you do 3?")
    r = await creator_client.get(f"{OFFERS}/{thread_id}")
    assert r.status_code == 200, r.text
    desk = r.json()
    assert desk["brand_note"] == "Can you do 3?"
    assert desk["changed"] == ["price_cents"]
    assert desk["their_ask"]["price_cents"] == 110000
    assert desk["terms_event_id"] == counter_id
    assert desk["latest"] is None  # the brand's terms are `their_ask`, not the creator's latest


async def test_other_creator_gets_404(new_creator_client, launched_batch, api_db):
    thread_id = launched_batch.threads["priyareviews"]
    await send_held(api_db, thread_id)
    r = await new_creator_client.get(f"{OFFERS}/{thread_id}")
    assert r.status_code == 404
    assert r.json()["detail"] == "not_found"
    assert (await new_creator_client.get(OFFERS)).json() == []


async def test_unsent_offer_desk_is_404(creator_client, launched_batch):
    r = await creator_client.get(f"{OFFERS}/{launched_batch.threads['priyareviews']}")
    assert r.status_code == 404


async def test_brand_gets_403(brand_client):
    r = await brand_client.get(OFFERS)
    assert r.status_code == 403
    assert r.json()["detail"] == "wrong_role"


async def test_desk_never_contains_ceiling_or_brand_contact(creator_client, launched_batch, api_db):
    thread_id = launched_batch.threads["priyareviews"]
    await send_held(api_db, thread_id)
    await record_brand_counter(api_db, thread_id, 110000, note="Can you do 3?")
    contact = await brief_contact_email(api_db, launched_batch.brief_id)
    raw = [
        (await creator_client.get(f"{OFFERS}/{thread_id}")).text,
        (await creator_client.get(OFFERS)).text,
    ]
    for text in raw:
        assert "123400" not in text
        assert "1,234" not in text
        assert "budget_ceiling" not in text
        if contact:
            assert contact not in text


async def test_unconfirmed_brand_latest_terms_do_not_drive_value_or_delta(
    creator_client, launched_batch, api_db
):
    """An agent's spoken offer (latest terms with source brand) is not the brand's offer."""
    thread_id = launched_batch.threads["priyareviews"]
    await send_held(api_db, thread_id)
    spoken = NegotiationTerms(
        videos=3, price_cents=111100, stance="offer", source="call", confidence=0.9
    )
    async with api_db.acquire() as conn:
        await repo.update_latest_terms(conn, thread_id, spoken, "brand")

    (item,) = _ours((await creator_client.get(OFFERS)).json(), launched_batch)
    assert item["total_value_cents"] == 100000
    desk = (await creator_client.get(f"{OFFERS}/{thread_id}")).json()
    assert desk["their_ask"]["price_cents"] == 100000
    assert desk["delta"]["latest_price_cents"] is None
    assert desk["latest"] is None


async def test_offer_desk_carries_the_raw_text_of_the_creators_email(
    creator_client, launched_batch, api_db
):
    thread_id = launched_batch.threads["priyareviews"]
    await send_held(api_db, thread_id)
    async with api_db.acquire() as conn:
        await conn.execute(
            "insert into public.transcripts (thread_id, kind, external_id, body_text, raw_text)"
            " values ($1, 'email_in', $2, 'Sounds good', 'Sounds good\n> old quote')",
            thread_id,
            f"offers-raw-{thread_id}",
        )

    r = await creator_client.get(f"{OFFERS}/{thread_id}")

    assert r.status_code == 200, r.text
    [transcript] = [t for t in r.json()["transcripts"] if t["kind"] == "email_in"]
    assert transcript["raw_text"] == "Sounds good\n> old quote"

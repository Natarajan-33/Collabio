"""The creator's offer actions: counter (with preview), accept and decline.

Priya's thread of the held `launched_batch` is moved to `awaiting_reply` with `send_held`.
Her floor for the thread's package is read here by SQL; it must never reach an event or an
outbox row.
"""

import asyncio
import json

import pytest

from app.core.money import format_cents
from app.modules.threads import repo
from tests.api.helpers import (
    events_of,
    outbox_of,
    record_brand_counter,
    send_held,
    thread_row,
)

pytestmark = pytest.mark.db

OFFERS = "/api/v1/offers"


async def floor_of(api_db, thread_id) -> tuple[int, int]:
    """(floor, package volume) of the thread's package."""
    async with api_db.acquire() as conn:
        row = await conn.fetchrow(
            "select f.floor_price_cents, p.volume_count from public.threads t"
            " join public.packages p on p.id = t.package_id"
            " join public.package_floors f on f.package_id = p.id where t.id = $1",
            thread_id,
        )
    assert row is not None, "Priya's package has no floor"
    return row["floor_price_cents"], row["volume_count"]


def scaled(floor: int, volume: int, videos: int) -> int:
    return -(-floor * videos // volume)


def counter_body(price_cents, *, based_on, videos=3, **extra):
    return {
        "terms": {"videos": videos, "price_cents": price_cents},
        "based_on_event_id": based_on,
    } | extra


@pytest.fixture
async def offer(launched_batch, api_db):
    """Priya's sent offer: (thread id, id of the `email_sent` event)."""
    thread_id = launched_batch.threads["priyareviews"]
    return thread_id, await send_held(api_db, thread_id)


async def test_counter_preview_warns_below_floor(creator_client, offer, api_db):
    thread_id, _ = offer
    floor, volume = await floor_of(api_db, thread_id)
    below = scaled(floor, volume, 3) - 100
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter/preview", json={"terms": {"videos": 3, "price_cents": below}}
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["below_floor_by_cents"] == 100
    assert preview["terms"]["stance"] == "counter"
    assert preview["terms"]["price_cents"] == below
    assert preview["delta"]["latest_price_cents"] == below

    ok = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter/preview",
        json={"terms": {"videos": 3, "price_cents": below + 100}},
    )
    assert ok.json()["below_floor_by_cents"] is None
    assert (await thread_row(api_db, thread_id))["status"] == "awaiting_reply"  # nothing written


async def test_counter_below_floor_needs_confirmation(creator_client, offer, api_db):
    thread_id, sent_id = offer
    floor, volume = await floor_of(api_db, thread_id)
    below = scaled(floor, volume, 3) - 100
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter", json=counter_body(below, based_on=sent_id)
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "below_floor"
    assert detail["below_by_cents"] == 100
    assert detail["message"]
    assert (await thread_row(api_db, thread_id))["status"] == "awaiting_reply"

    confirmed = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter",
        json=counter_body(below, based_on=sent_id, confirm_below_floor=True),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "countered"


async def test_counter_records_event_and_notifies(creator_client, offer, api_db):
    thread_id, sent_id = offer
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter",
        json=counter_body(120000, videos=2, based_on=sent_id, note="Two is my sweet spot"),
    )
    assert r.status_code == 200, r.text
    desk = r.json()
    assert desk["status"] == "countered"
    assert desk["waiting_on"] == "brand"
    assert desk["latest"]["price_cents"] == 120000
    assert desk["latest_source"] == "creator"
    assert desk["allowed_actions"] == ["counter", "decline"]
    assert desk["expires_at"] is None

    (event,) = await events_of(api_db, thread_id, "counter_submitted")
    assert event["actor"] == "creator"
    assert event["terms"]["source"] == "in_app"
    assert event["terms"]["stance"] == "counter"
    assert event["terms"]["price_cents"] == 120000
    assert event["payload"]["note"] == "Two is my sweet spot"
    assert desk["terms_event_id"] == event["id"]

    (row,) = await outbox_of(api_db, thread_id)
    assert row["kind"] == "brand_creator_countered"
    assert row["event_id"] == event["id"]
    thread = await thread_row(api_db, thread_id)
    assert thread["status"] == "countered"
    assert thread["expires_at"] is None
    assert thread["latest_terms_source"] == "creator"


async def test_counter_revision_from_countered(creator_client, offer, api_db):
    thread_id, sent_id = offer
    first = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter", json=counter_body(120000, videos=2, based_on=sent_id)
    )
    assert first.status_code == 200, first.text
    second = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter",
        json=counter_body(130000, videos=2, based_on=first.json()["terms_event_id"]),
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "countered"
    assert second.json()["latest"]["price_cents"] == 130000
    assert len(await events_of(api_db, thread_id, "counter_submitted")) == 2


async def test_stale_counter_409(creator_client, offer, api_db):
    thread_id, sent_id = offer
    counter_id = await record_brand_counter(api_db, thread_id, 110000)
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter", json=counter_body(120000, videos=2, based_on=sent_id)
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "terms_changed"
    assert detail["terms_event_id"] == counter_id
    assert await events_of(api_db, thread_id, "counter_submitted") == []
    assert (await thread_row(api_db, thread_id))["status"] == "awaiting_reply"


async def test_accept_records_brand_offer(creator_client, offer, api_db):
    thread_id, sent_id = offer
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/accept", json={"based_on_event_id": sent_id}
    )
    assert r.status_code == 200, r.text
    desk = r.json()
    assert desk["status"] == "accepted"
    assert desk["waiting_on"] == "brand"
    assert desk["allowed_actions"] == ["decline"]

    thread = await thread_row(api_db, thread_id)
    latest = json.loads(thread["latest_terms"])
    assert (latest["videos"], latest["price_cents"], latest["stance"]) == (3, 100000, "accept")
    assert thread["latest_terms_source"] == "creator"
    (event,) = await events_of(api_db, thread_id, "accepted")
    assert event["actor"] == "creator"
    assert event["terms"]["stance"] == "accept"
    (row,) = await outbox_of(api_db, thread_id)
    assert row["kind"] == "brand_creator_accepted"
    assert row["event_id"] == event["id"]


async def test_accept_after_brand_counter_uses_counter(creator_client, offer, api_db):
    thread_id, _ = offer
    counter_id = await record_brand_counter(api_db, thread_id, 110000)
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/accept", json={"based_on_event_id": counter_id}
    )
    assert r.status_code == 200, r.text
    assert r.json()["latest"]["price_cents"] == 110000
    latest = json.loads((await thread_row(api_db, thread_id))["latest_terms"])
    assert (latest["videos"], latest["price_cents"], latest["stance"]) == (3, 110000, "accept")


async def test_decline_with_reason(creator_client, offer, api_db):
    thread_id, _ = offer
    r = await creator_client.post(f"{OFFERS}/{thread_id}/decline", json={"reason": "Booked solid"})
    assert r.status_code == 200, r.text
    desk = r.json()
    assert desk["status"] == "declined"
    assert desk["waiting_on"] == "none"
    assert desk["allowed_actions"] == []
    (event,) = await events_of(api_db, thread_id, "declined")
    assert event["actor"] == "creator"
    assert event["payload"]["reason"] == "Booked solid"
    (row,) = await outbox_of(api_db, thread_id)
    assert row["kind"] == "brand_creator_declined"
    assert row["payload"] == {"reason": "Booked solid"}
    assert (await thread_row(api_db, thread_id))["expires_at"] is None


async def test_decline_without_reason(creator_client, offer, api_db):
    thread_id, _ = offer
    r = await creator_client.post(f"{OFFERS}/{thread_id}/decline", json={})
    assert r.status_code == 200, r.text
    (event,) = await events_of(api_db, thread_id, "declined")
    assert "reason" not in event["payload"]


async def test_decline_after_accept_allowed(creator_client, offer, api_db):
    thread_id, sent_id = offer
    accepted = await creator_client.post(
        f"{OFFERS}/{thread_id}/accept", json={"based_on_event_id": sent_id}
    )
    assert accepted.status_code == 200, accepted.text
    r = await creator_client.post(f"{OFFERS}/{thread_id}/decline", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "declined"


async def test_accept_not_allowed_when_countered(creator_client, offer, api_db):
    thread_id, sent_id = offer
    countered = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter", json=counter_body(120000, videos=2, based_on=sent_id)
    )
    current = countered.json()["terms_event_id"]
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/accept", json={"based_on_event_id": current}
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "action_not_allowed"
    assert (await thread_row(api_db, thread_id))["status"] == "countered"


async def test_double_accept_one_event(creator_client, offer, api_db):
    thread_id, sent_id = offer
    body = {"based_on_event_id": sent_id}
    first, second = await asyncio.gather(
        creator_client.post(f"{OFFERS}/{thread_id}/accept", json=body),
        creator_client.post(f"{OFFERS}/{thread_id}/accept", json=body),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    assert len(await events_of(api_db, thread_id, "accepted")) == 1
    assert len(await outbox_of(api_db, thread_id)) == 1


async def test_late_counter_reopens_no_response(creator_client, offer, api_db):
    thread_id, sent_id = offer
    async with api_db.acquire() as conn:
        ref = await repo.load_ref(conn, thread_id)
        await repo.apply_event_id(
            conn,
            ref,
            expected={"awaiting_reply"},
            target="no_response",
            type="offer_expired",
            actor="system",
        )
    assert (await thread_row(api_db, thread_id))["status"] == "no_response"
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter", json=counter_body(120000, videos=2, based_on=sent_id)
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "countered"
    assert (await thread_row(api_db, thread_id))["expires_at"] is None


async def test_floor_never_in_events_or_outbox(creator_client, offer, api_db):
    thread_id, sent_id = offer
    floor, volume = await floor_of(api_db, thread_id)
    below = scaled(floor, volume, 3) - 100
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter",
        json=counter_body(below, based_on=sent_id, confirm_below_floor=True, note="Final answer"),
    )
    assert r.status_code == 200, r.text
    stored = json.dumps(
        [(e["payload"], e["terms"]) for e in await events_of(api_db, thread_id)]
        + [(o["kind"], o["payload"]) for o in await outbox_of(api_db, thread_id)]
    )
    for secret in {floor, scaled(floor, volume, 3)}:
        assert str(secret) not in stored
        assert format_cents(secret) not in stored
        assert f"{secret:,}" not in stored


async def test_other_creator_cannot_act(new_creator_client, offer, api_db):
    thread_id, sent_id = offer
    for path, body in (
        ("counter/preview", {"terms": {"videos": 3, "price_cents": 90000}}),
        ("counter", counter_body(90000, based_on=sent_id)),
        ("accept", {"based_on_event_id": sent_id}),
        ("decline", {}),
    ):
        r = await new_creator_client.post(f"{OFFERS}/{thread_id}/{path}", json=body)
        assert r.status_code == 404, (path, r.text)
        assert r.json()["detail"] == "not_found"
    assert (await thread_row(api_db, thread_id))["status"] == "awaiting_reply"


async def test_brand_cannot_act(brand_client, offer):
    thread_id, sent_id = offer
    r = await brand_client.post(f"{OFFERS}/{thread_id}/accept", json={"based_on_event_id": sent_id})
    assert r.status_code == 403


async def test_counter_validation(creator_client, offer):
    thread_id, sent_id = offer
    too_cheap = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter", json=counter_body(50, based_on=sent_id)
    )
    assert too_cheap.status_code == 422
    long_note = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter",
        json=counter_body(120000, videos=2, based_on=sent_id, note="x" * 1001),
    )
    assert long_note.status_code == 422


async def test_stale_accept_409(creator_client, offer, api_db):
    thread_id, sent_id = offer
    counter_id = await record_brand_counter(api_db, thread_id, 110000)
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/accept", json={"based_on_event_id": sent_id}
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "terms_changed"
    assert detail["terms_event_id"] == counter_id
    assert await events_of(api_db, thread_id, "accepted") == []
    assert (await thread_row(api_db, thread_id))["status"] == "awaiting_reply"

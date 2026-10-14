"""The brand's actions on the board: counter (with preview), resolve, decline / withdraw and
decline-the-rest.

Priya's thread of the held `launched_batch` is moved to `awaiting_reply` with `send_held`; the
creator's own moves go through the offers endpoints with `creator_client`. The brief's ceiling
is $1,234 for three videos (123400 cents) and must never reach an event or an outbox row.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.board.actions import BoardActions
from app.modules.threads import repo
from tests.api.helpers import events_of, force_status, outbox_of, send_held, thread_row

pytestmark = pytest.mark.db

BATCHES = "/api/v1/batches"
THREADS = "/api/v1/threads"


def counter_body(price_cents, *, based_on, videos=3, **extra):
    return {
        "terms": {"videos": videos, "price_cents": price_cents},
        "based_on_event_id": based_on,
    } | extra


async def post(client, path, body=None):
    return await client.post(path) if body is None else await client.post(path, json=body)


@pytest.fixture
async def needs_review(offer, api_db):
    """Priya's offer forced to `needs_review`, as an unreadable email reply would leave it:
    (thread id, id of the newest terms event, which is still the `email_sent`)."""
    thread_id, sent_id = offer
    await force_status(
        api_db,
        thread_id,
        "needs_review",
        event="needs_review",
        payload={"reason": "The reply has no price"},
    )
    return thread_id, sent_id


async def test_card_has_actions_expiry_and_terms_event(brand_client, launched_batch, offer):
    thread_id, sent_id = offer
    r = await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")
    view = r.json()
    card = next(t for t in view["threads"] if t["id"] == str(thread_id))
    assert card["allowed_actions"] == ["withdraw"]
    assert card["expires_at"] is not None
    assert card["terms_event_id"] == sent_id
    assert card["deal_id"] is None
    assert view["brief"]["hires_target"] == 1
    assert view["kpis"]["hired"] == 0
    queued = next(t for t in view["threads"] if t["id"] != str(thread_id))
    assert queued["allowed_actions"] == ["withdraw"]
    assert queued["expires_at"] is None
    assert queued["terms_event_id"] is None


async def test_brand_counter_above_ceiling_rejected(brand_client, countered, api_db):
    thread_id, counter_id = countered
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/counter", json=counter_body(130000, based_on=counter_id)
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "above_ceiling"
    assert "$1,234" in detail["message"]
    assert (await thread_row(api_db, thread_id))["status"] == "countered"
    assert await events_of(api_db, thread_id, "brand_counter_sent") == []


async def test_counter_preview_shows_delta_and_ceiling(brand_client, countered, api_db):
    thread_id, _ = countered
    over = await brand_client.post(
        f"{THREADS}/{thread_id}/counter/preview",
        json={"terms": {"videos": 3, "price_cents": 130000}},
    )
    assert over.status_code == 200, over.text
    preview = over.json()
    assert "$1,234" in preview["ceiling_violation"]
    assert preview["terms"]["stance"] == "offer"
    assert preview["delta"]["latest_price_cents"] == 130000
    ok = await brand_client.post(
        f"{THREADS}/{thread_id}/counter/preview",
        json={"terms": {"videos": 3, "price_cents": 110000}},
    )
    assert ok.json()["ceiling_violation"] is None
    assert await events_of(api_db, thread_id, "brand_counter_sent") == []  # nothing written


async def test_brand_counter_moves_to_awaiting_reply(brand_client, countered, api_db):
    thread_id, counter_id = countered
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/counter",
        json=counter_body(110000, based_on=counter_id, note="Meet me here?"),
    )
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["id"] == str(thread_id)
    assert card["status"] == "awaiting_reply"
    assert card["allowed_actions"] == ["withdraw"]
    assert card["expires_at"] is not None
    assert card["latest_terms"]["price_cents"] == 110000
    assert card["latest_terms_source"] == "brand"

    (event,) = await events_of(api_db, thread_id, "brand_counter_sent")
    assert event["actor"] == "brand"
    assert event["terms"]["stance"] == "offer"
    assert event["terms"]["source"] == "in_app"
    assert event["terms"]["price_cents"] == 110000
    assert event["payload"]["note"] == "Meet me here?"
    assert card["terms_event_id"] == event["id"]

    (row,) = [
        o for o in await outbox_of(api_db, thread_id) if o["kind"] == "creator_brand_countered"
    ]
    assert row["event_id"] == event["id"]
    assert row["payload"] == {"note": "Meet me here?"}
    thread = await thread_row(api_db, thread_id)
    assert thread["status"] == "awaiting_reply"
    assert thread["expires_at"] is not None


async def test_brand_counter_payload_has_no_ceiling(brand_client, countered, api_db):
    thread_id, counter_id = countered
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/counter",
        json=counter_body(110000, based_on=counter_id, note="Best I can do"),
    )
    assert r.status_code == 200, r.text
    stored = json.dumps(
        [(e["payload"], e["terms"]) for e in await events_of(api_db, thread_id)]
        + [(o["kind"], o["payload"]) for o in await outbox_of(api_db, thread_id)]
    )
    assert "123400" not in stored
    assert "1,234" not in stored
    assert "$1234" not in stored


async def test_counter_stale_409(brand_client, countered, offer, api_db):
    thread_id, counter_id = countered
    _, sent_id = offer
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/counter", json=counter_body(110000, based_on=sent_id)
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "terms_changed"
    assert r.json()["detail"]["terms_event_id"] == counter_id
    assert await events_of(api_db, thread_id, "brand_counter_sent") == []


async def test_counter_not_allowed_while_awaiting_reply(brand_client, offer, api_db):
    thread_id, sent_id = offer
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/counter", json=counter_body(110000, based_on=sent_id)
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "action_not_allowed"
    assert (await thread_row(api_db, thread_id))["status"] == "awaiting_reply"


async def test_resolve_needs_review_counter(brand_client, needs_review, api_db):
    thread_id, sent_id = needs_review
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/resolve",
        json={
            "outcome": "counter",
            "terms": {"videos": 3, "price_cents": 105000},
            "based_on_event_id": sent_id,
        },
    )
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["status"] == "countered"
    assert card["latest_terms"]["price_cents"] == 105000
    assert card["latest_terms_source"] == "creator"
    (event,) = await events_of(api_db, thread_id, "counter_submitted")
    assert event["actor"] == "brand"
    assert event["payload"]["resolved_review"] is True
    assert event["terms"]["stance"] == "counter"
    assert event["terms"]["price_cents"] == 105000
    assert (await thread_row(api_db, thread_id))["expires_at"] is None


async def test_resolve_accept_uses_brand_offer(brand_client, needs_review, api_db):
    thread_id, sent_id = needs_review
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/resolve",
        json={"outcome": "accept", "based_on_event_id": sent_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"
    (event,) = await events_of(api_db, thread_id, "accepted")
    assert event["actor"] == "brand"
    assert event["payload"]["resolved_review"] is True
    assert (event["terms"]["videos"], event["terms"]["price_cents"]) == (3, 100000)
    assert event["terms"]["stance"] == "accept"
    latest = json.loads((await thread_row(api_db, thread_id))["latest_terms"])
    assert (latest["price_cents"], latest["stance"]) == (100000, "accept")


async def test_resolve_decline(brand_client, needs_review, api_db):
    thread_id, sent_id = needs_review
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/resolve",
        json={"outcome": "decline", "based_on_event_id": sent_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "declined"
    (event,) = await events_of(api_db, thread_id, "declined")
    assert event["actor"] == "brand"
    assert event["payload"]["resolved_review"] is True


async def test_resolve_counter_requires_terms(brand_client, needs_review, api_db):
    thread_id, sent_id = needs_review
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/resolve", json={"outcome": "counter", "based_on_event_id": sent_id}
    )
    assert r.status_code == 422, r.text
    assert (await thread_row(api_db, thread_id))["status"] == "needs_review"


async def test_resolve_only_from_needs_review(brand_client, offer):
    thread_id, sent_id = offer
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/resolve", json={"outcome": "accept", "based_on_event_id": sent_id}
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "action_not_allowed"


async def test_withdraw_awaiting_reply(brand_client, offer, api_db):
    thread_id, _ = offer
    r = await brand_client.post(f"{THREADS}/{thread_id}/decline", json={"reason": "Changed plans"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["status"] == "closed_lost"
    assert card["allowed_actions"] == []
    assert card["expires_at"] is None
    (event,) = await events_of(api_db, thread_id, "closed_lost")
    assert event["actor"] == "brand"
    assert event["payload"]["reason"] == "withdrawn"
    (row,) = [o for o in await outbox_of(api_db, thread_id) if o["kind"] == "creator_closed"]
    assert row["event_id"] == event["id"]
    assert row["payload"] == {"reason": "withdrawn"}


async def test_withdraw_queued(brand_client, launched_batch, api_db):
    thread_id = launched_batch.threads["mayamakestech"]
    r = await brand_client.post(f"{THREADS}/{thread_id}/decline", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed_lost"
    (event,) = await events_of(api_db, thread_id, "closed_lost")
    assert event["payload"]["reason"] == "withdrawn"
    # The creator never heard of this offer: no "thanks for considering" mail.
    assert await outbox_of(api_db, thread_id) == []


async def test_decline_countered_reason(brand_client, countered, api_db):
    thread_id, _ = countered
    r = await brand_client.post(f"{THREADS}/{thread_id}/decline", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed_lost"
    (event,) = await events_of(api_db, thread_id, "closed_lost")
    assert event["payload"]["reason"] == "declined_by_brand"
    (row,) = [o for o in await outbox_of(api_db, thread_id) if o["kind"] == "creator_closed"]
    assert row["payload"] == {"reason": "declined_by_brand"}


async def test_decline_reason_stays_private(brand_client, offer, api_db):
    thread_id, _ = offer
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/decline", json={"reason": "Over budget at $1,234"}
    )
    assert r.status_code == 200, r.text
    stored = json.dumps(
        [e["payload"] for e in await events_of(api_db, thread_id)]
        + [o["payload"] for o in await outbox_of(api_db, thread_id)]
    )
    assert "Over budget" not in stored


async def test_withdraw_not_allowed_while_drafting(brand_client, launched_batch, api_db):
    thread_id = launched_batch.threads["mayamakestech"]
    async with api_db.acquire() as conn:
        await repo.transition(conn, thread_id, expected={"queued"}, target="drafting")
    r = await brand_client.post(f"{THREADS}/{thread_id}/decline", json={})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "action_not_allowed"
    assert (await thread_row(api_db, thread_id))["status"] == "drafting"


async def test_decline_twice_second_409(brand_client, offer):
    thread_id, _ = offer
    first = await brand_client.post(f"{THREADS}/{thread_id}/decline", json={})
    second = await brand_client.post(f"{THREADS}/{thread_id}/decline", json={})
    assert (first.status_code, second.status_code) == (200, 409)


async def test_decline_rest_preview_and_isolation(brand_client, launched_ten, api_db, monkeypatch):
    ids = list(launched_ten.threads.values())
    sent, drafting, awarded, queued = ids[:3], ids[3], ids[4], ids[5:]
    failed_before = queued[0]  # a thread that failed before anything reached the creator
    queued = queued[1:]
    async with api_db.acquire() as conn:
        await repo.transition(conn, failed_before, expected={"queued"}, target="drafting")
        await repo.transition(conn, failed_before, expected={"drafting"}, target="failed")
    for thread_id in sent:
        await send_held(api_db, thread_id)
    async with api_db.acquire() as conn:
        await repo.transition(conn, drafting, expected={"queued"}, target="drafting")
    await send_held(api_db, awarded)
    await force_status(api_db, awarded, "countered", event="counter_submitted", actor="creator")
    await force_status(api_db, awarded, "awarded", event="awarded", actor="brand")

    base = f"{BATCHES}/{launched_ten.batch_id}/decline-rest"
    r = await brand_client.post(f"{base}/preview")
    assert r.status_code == 200, r.text
    preview = r.json()
    will_close = {i["thread_id"] for i in preview["will_close"]}
    skipped = {i["thread_id"]: i["status"] for i in preview["skipped"]}
    assert will_close == {str(t) for t in sent + queued + [failed_before]}
    assert skipped == {str(drafting): "drafting", str(awarded): "awarded"}
    assert all(i["creator"]["handle"] for i in preview["will_close"])
    assert all(i["status"] in {"awaiting_reply", "queued", "failed"} for i in preview["will_close"])

    bad = sent[1]
    original = BoardActions._close_not_selected

    async def flaky(self, thread_id):
        if thread_id == bad:
            raise RuntimeError("boom")
        return await original(self, thread_id)

    monkeypatch.setattr(BoardActions, "_close_not_selected", flaky)
    done = await brand_client.post(base)
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["failed"] == [str(bad)]
    assert set(result["closed"]) == {str(t) for t in sent + queued + [failed_before]} - {str(bad)}

    for thread_id in result["closed"]:
        row = await thread_row(api_db, thread_id)
        assert row["status"] == "closed_lost"
        (event,) = await events_of(api_db, thread_id, "closed_lost")
        assert event["payload"]["reason"] == "not_selected"
        mail = [o for o in await outbox_of(api_db, thread_id) if o["kind"] == "creator_closed"]
        if UUID(thread_id) in queued + [failed_before]:
            assert mail == []  # never contacted: the event is recorded, no mail
        else:
            (out,) = mail
            assert out["payload"] == {"reason": "not_selected"}
    assert (await thread_row(api_db, bad))["status"] == "awaiting_reply"
    assert (await thread_row(api_db, drafting))["status"] == "drafting"
    assert (await thread_row(api_db, awarded))["status"] == "awarded"

    again = await brand_client.post(f"{base}/preview")
    assert {i["thread_id"] for i in again.json()["will_close"]} == {str(bad)}


async def test_kpis_hired_and_replied(brand_client, launched_batch, countered, api_db):
    priya, _ = countered
    arjun = launched_batch.threads["arjuntech"]
    await force_status(api_db, priya, "awarded", event="awarded", actor="brand")
    await send_held(api_db, arjun)
    await force_status(api_db, arjun, None, event="email_received", actor="creator")

    r = await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")
    kpis = r.json()["kpis"]
    assert kpis["hired"] == 1
    assert kpis["replied"] == 2  # the counter and the email reply
    listing = await brand_client.get(BATCHES)
    mine = next(i for i in listing.json() if i["id"] == str(launched_batch.batch_id))
    assert mine["replied"] == 2


async def test_other_brand_404(new_brand_client, launched_batch, offer):
    thread_id, sent_id = offer
    batch_id = launched_batch.batch_id
    for path, body in (
        (f"{THREADS}/{thread_id}/counter/preview", {"terms": {"videos": 3, "price_cents": 90000}}),
        (f"{THREADS}/{thread_id}/counter", counter_body(90000, based_on=sent_id)),
        (f"{THREADS}/{thread_id}/resolve", {"outcome": "decline", "based_on_event_id": sent_id}),
        (f"{THREADS}/{thread_id}/decline", {}),
        (f"{BATCHES}/{batch_id}/decline-rest/preview", None),
        (f"{BATCHES}/{batch_id}/decline-rest", None),
    ):
        r = await post(new_brand_client, path, body)
        assert r.status_code == 404, (path, r.text)


async def test_creator_403(creator_client, launched_batch, offer):
    thread_id, _ = offer
    for path, body in (
        (f"{THREADS}/{thread_id}/decline", {}),
        (f"{BATCHES}/{launched_batch.batch_id}/decline-rest", None),
    ):
        r = await post(creator_client, path, body)
        assert r.status_code == 403, (path, r.text)


# Decline the rest of the batch, only the threads the brand saw -----------------------------


async def test_decline_rest_preview_marks_threads_in_progress(brand_client, launched_ten, api_db):
    ids = list(launched_ten.threads.values())
    drafting, calling, sent = ids[0], ids[1], ids[2]
    async with api_db.acquire() as conn:
        await repo.transition(conn, drafting, expected={"queued"}, target="drafting")
        await repo.transition(conn, calling, expected={"queued"}, target="calling")
    await send_held(api_db, sent)

    r = await brand_client.post(f"{BATCHES}/{launched_ten.batch_id}/decline-rest/preview")

    preview = r.json()
    live = {i["thread_id"]: i["status"] for i in preview["skipped"] if i["in_progress"]}
    assert live == {str(drafting): "drafting", str(calling): "calling"}
    assert not any(i["in_progress"] for i in preview["will_close"])


async def test_decline_rest_closes_only_the_named_threads_that_are_still_open(
    brand_client, launched_ten, api_db
):
    ids = list(launched_ten.threads.values())
    named_open, named_moved, unnamed, outsider = ids[0], ids[1], ids[2], uuid4()
    for thread_id in (named_open, named_moved, unnamed):
        await send_held(api_db, thread_id)
    await force_status(
        api_db,
        named_moved,
        "closed_lost",
        event="closed_lost",
        actor="brand",
        payload={"reason": "withdrawn"},
    )

    r = await brand_client.post(
        f"{BATCHES}/{launched_ten.batch_id}/decline-rest",
        json={"thread_ids": [str(named_open), str(named_moved), str(outsider)]},
    )

    assert r.status_code == 200, r.text
    result = r.json()
    assert result["closed"] == [str(named_open)]
    assert result["failed"] == []
    assert set(result["skipped"]) == {str(named_moved), str(outsider)}
    assert (await thread_row(api_db, named_open))["status"] == "closed_lost"
    assert (await thread_row(api_db, unnamed))["status"] == "awaiting_reply"  # not previewed


async def test_decline_rest_skips_a_named_thread_that_became_live(
    brand_client, launched_ten, api_db
):
    ids = list(launched_ten.threads.values())
    queued, sent = ids[0], ids[1]
    await send_held(api_db, sent)
    async with api_db.acquire() as conn:
        await repo.transition(conn, queued, expected={"queued"}, target="drafting")

    r = await brand_client.post(
        f"{BATCHES}/{launched_ten.batch_id}/decline-rest",
        json={"thread_ids": [str(queued), str(sent)]},
    )

    result = r.json()
    assert result["closed"] == [str(sent)]
    assert result["skipped"] == [str(queued)]
    assert (await thread_row(api_db, queued))["status"] == "drafting"


async def test_decline_rest_without_a_body_still_closes_every_open_thread(
    brand_client, launched_ten, api_db
):
    ids = list(launched_ten.threads.values())
    await send_held(api_db, ids[0])

    r = await brand_client.post(f"{BATCHES}/{launched_ten.batch_id}/decline-rest")

    result = r.json()
    assert str(ids[0]) in result["closed"]
    assert len(result["closed"]) == len(ids)
    assert result["skipped"] == []


# Counter bounds ----------------------------------------------------------------------------


def yesterday() -> str:
    return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


def today() -> str:
    return datetime.now(UTC).date().isoformat()


async def test_brand_counter_with_a_past_go_live_is_422(brand_client, countered, api_db):
    thread_id, sent_id = countered
    body = counter_body(90000, based_on=sent_id)
    body["terms"]["go_live_by"] = yesterday()

    r = await brand_client.post(f"{THREADS}/{thread_id}/counter", json=body)

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == {
        "code": "go_live_in_past",
        "message": "The go-live date has passed",
    }
    assert await events_of(api_db, thread_id, "brand_counter_sent") == []


async def test_brand_counter_going_live_today_is_fine(brand_client, countered):
    thread_id, sent_id = countered
    body = counter_body(90000, based_on=sent_id)
    body["terms"]["go_live_by"] = today()

    r = await brand_client.post(f"{THREADS}/{thread_id}/counter", json=body)

    assert r.status_code == 200, r.text


async def test_brand_counter_price_over_the_bound_is_422(brand_client, countered):
    thread_id, sent_id = countered

    r = await brand_client.post(
        f"{THREADS}/{thread_id}/counter", json=counter_body(100_000_001, based_on=sent_id)
    )

    assert r.status_code == 422, r.text


async def test_resolve_counter_with_a_past_go_live_is_422(brand_client, needs_review, api_db):
    thread_id, sent_id = needs_review

    r = await brand_client.post(
        f"{THREADS}/{thread_id}/resolve",
        json={
            "outcome": "counter",
            "terms": {"videos": 3, "price_cents": 105000, "go_live_by": yesterday()},
            "based_on_event_id": sent_id,
        },
    )

    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "go_live_in_past"
    assert (await thread_row(api_db, thread_id))["status"] == "needs_review"

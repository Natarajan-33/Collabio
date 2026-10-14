"""Award: preview, the deal and its milestones, and the checks that stand in front of them.

Priya's offer is countered at 3 videos for $1,200 (the `countered` fixture); the brief's private
ceiling is $1,234 for three videos and its hire target is 1. Other threads are countered through
the thread repo, as an email or call reply would leave them.
"""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.threads import repo
from app.schemas.negotiation import NegotiationTerms
from tests.api.helpers import events_of, force_status, outbox_of, send_held, thread_row

pytestmark = pytest.mark.db

THREADS = "/api/v1/threads"
BATCHES = "/api/v1/batches"
OFFERS = "/api/v1/offers"


def milestones(amounts, due: date, *, spread_days: int = 0) -> list[dict]:
    return [
        {
            "seq": i,
            "title": f"Video {i}",
            "amount_cents": amount,
            "due_date": (due + timedelta(days=spread_days * (i - 1))).isoformat(),
        }
        for i, amount in enumerate(amounts, start=1)
    ]


def award_body(drafts, *, based_on, **extra):
    return {"milestones": drafts, "based_on_event_id": based_on} | extra


async def go_live_of(brand_client, batch_id) -> date:
    r = await brand_client.get(f"{BATCHES}/{batch_id}")
    return date.fromisoformat(r.json()["brief"]["go_live_by"])


async def force_counter(api_db, thread_id, price_cents, *, videos=3) -> int:
    """Send a held thread's offer, then record a creator counter on it (as an email reply
    would). Returns the counter's event id."""
    await send_held(api_db, thread_id)
    terms = NegotiationTerms(
        videos=videos,
        price_cents=price_cents,
        stance="counter",
        source="email",
        confidence=0.95,
    )
    async with api_db.acquire() as conn:
        ref = await repo.load_ref(conn, thread_id)
        event_id = await repo.apply_event_id(
            conn,
            ref,
            expected={"awaiting_reply"},
            target="countered",
            type="counter_submitted",
            actor="creator",
            terms=terms,
            latest_terms=terms,
            latest_terms_source="creator",
        )
    assert event_id is not None
    return event_id


async def deals_of(api_db, thread_id):
    async with api_db.acquire() as conn:
        deals = await conn.fetch("select * from public.deals where thread_id = $1", thread_id)
        rows = await conn.fetch(
            "select m.seq, m.title, m.amount_cents, m.due_date, m.status"
            " from public.deal_milestones m join public.deals d on d.id = m.deal_id"
            " where d.thread_id = $1 order by m.seq",
            thread_id,
        )
    return deals, rows


async def test_award_preview_from_counter(brand_client, launched_batch, countered, api_db):
    thread_id, counter_id = countered
    go_live = await go_live_of(brand_client, launched_batch.batch_id)
    r = await brand_client.post(f"{THREADS}/{thread_id}/award/preview")
    assert r.status_code == 200, r.text
    preview = r.json()
    agreed = preview["agreed"]
    assert (agreed["videos"], agreed["price_cents"], agreed["format"]) == (3, 120000, "short_video")
    assert agreed["go_live_by"] == go_live.isoformat()  # the counter named no date: the brief's
    assert [m["amount_cents"] for m in preview["milestones"]] == [40000] * 3
    assert [m["title"] for m in preview["milestones"]] == ["Video 1", "Video 2", "Video 3"]
    assert {m["due_date"] for m in preview["milestones"]} == {go_live.isoformat()}
    assert preview["over_ceiling_cents"] is None
    assert (preview["hired"], preview["hires_target"]) == (0, 1)
    assert preview["would_reach_target"] is True
    assert preview["over_target"] is False
    assert preview["terms_event_id"] == counter_id
    assert {c["handle"] for c in preview["open_others"]} == {"arjuntech", "mayamakestech"}
    assert (await thread_row(api_db, thread_id))[
        "status"
    ] == "countered"  # a preview writes nothing


async def test_award_creates_deal_and_milestones(
    brand_client, creator_client, launched_batch, countered, api_db
):
    thread_id, counter_id = countered
    preview = (await brand_client.post(f"{THREADS}/{thread_id}/award/preview")).json()
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/award", json=award_body(preview["milestones"], based_on=counter_id)
    )
    assert r.status_code == 200, r.text
    deal = r.json()
    assert deal["status"] == "booked"
    assert deal["thread_id"] == str(thread_id)
    assert deal["batch_id"] == str(launched_batch.batch_id)
    assert deal["terms"]["price_cents"] == 120000
    assert [m["amount_cents"] for m in deal["milestones"]] == [40000] * 3
    assert {m["status"] for m in deal["milestones"]} == {"pending"}
    assert deal["creator_handle"] == "priyareviews"

    async with api_db.acquire() as conn:
        creator_email = await conn.fetchval(
            "select c.email from public.creators c join public.threads t on t.creator_id = c.id"
            " where t.id = $1",
            thread_id,
        )
        contact_email = await conn.fetchval(
            "select contact_email from public.briefs where id = $1", launched_batch.brief_id
        )
    assert creator_email and contact_email
    assert deal["creator"]["email"] == creator_email
    assert deal["brand"]["email"] == contact_email

    assert (await thread_row(api_db, thread_id))["status"] == "awarded"
    (event,) = await events_of(api_db, thread_id, "awarded")
    assert event["actor"] == "brand"
    assert event["terms"]["stance"] == "accept"
    assert event["terms"]["source"] == "in_app"
    assert event["terms"]["price_cents"] == 120000
    (row,) = [o for o in await outbox_of(api_db, thread_id) if o["kind"] == "creator_awarded"]
    assert row["event_id"] == event["id"]
    deals, rows = await deals_of(api_db, thread_id)
    (stored,) = deals
    assert str(stored["id"]) == deal["id"]
    assert stored["awarded_event_id"] == event["id"]
    assert [r["amount_cents"] for r in rows] == [40000] * 3

    # The ceiling stays out of the event and the notification.
    leaked = json.dumps(
        [(e["payload"], e["terms"]) for e in await events_of(api_db, thread_id)]
        + [o["payload"] for o in await outbox_of(api_db, thread_id)]
    )
    assert "123400" not in leaked and "1,234" not in leaked

    card = next(
        t
        for t in (await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")).json()["threads"]
        if t["id"] == str(thread_id)
    )
    assert card["status"] == "awarded"
    assert card["deal_id"] == deal["id"]
    assert card["allowed_actions"] == []


async def test_award_edited_milestones(brand_client, launched_batch, countered, api_db):
    thread_id, counter_id = countered
    go_live = await go_live_of(brand_client, launched_batch.batch_id)
    drafts = milestones([50000, 35000, 35000], go_live + timedelta(days=3), spread_days=7)
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/award", json=award_body(drafts, based_on=counter_id)
    )
    assert r.status_code == 200, r.text
    assert [m["amount_cents"] for m in r.json()["milestones"]] == [50000, 35000, 35000]
    _, rows = await deals_of(api_db, thread_id)
    assert [r["due_date"] for r in rows] == [
        go_live + timedelta(days=3),
        go_live + timedelta(days=10),
        go_live + timedelta(days=17),
    ]


async def test_award_invalid_milestones(brand_client, launched_batch, countered, api_db):
    thread_id, counter_id = countered
    go_live = await go_live_of(brand_client, launched_batch.batch_id)
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/award",
        json=award_body(milestones([50000, 35000, 30000], go_live), based_on=counter_id),
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "milestones_invalid"
    assert detail["message"]
    assert any("$1,150" in e and "$1,200" in e for e in detail["errors"])
    early = await brand_client.post(
        f"{THREADS}/{thread_id}/award",
        json=award_body(milestones([40000] * 3, go_live - timedelta(days=1)), based_on=counter_id),
    )
    assert early.status_code == 422
    assert len(early.json()["detail"]["errors"]) == 3

    assert (await thread_row(api_db, thread_id))["status"] == "countered"
    assert await events_of(api_db, thread_id, "awarded") == []
    assert (await deals_of(api_db, thread_id))[0] == []
    assert [o for o in await outbox_of(api_db, thread_id) if o["kind"] == "creator_awarded"] == []


async def test_award_over_ceiling_needs_confirmation(
    brand_client, creator_client, launched_batch, offer, api_db
):
    thread_id, sent_id = offer
    r = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter",
        json={"terms": {"videos": 3, "price_cents": 130000}, "based_on_event_id": sent_id},
    )
    counter_id = r.json()["terms_event_id"]
    preview = (await brand_client.post(f"{THREADS}/{thread_id}/award/preview")).json()
    assert preview["over_ceiling_cents"] == 6600

    body = award_body(preview["milestones"], based_on=counter_id)
    refused = await brand_client.post(f"{THREADS}/{thread_id}/award", json=body)
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "over_ceiling"
    assert detail["over_by_cents"] == 6600
    assert (await thread_row(api_db, thread_id))["status"] == "countered"

    confirmed = await brand_client.post(
        f"{THREADS}/{thread_id}/award", json=body | {"confirm_over_ceiling": True}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["terms"]["price_cents"] == 130000


async def test_award_incomplete_terms(brand_client, launched_batch, offer, api_db):
    thread_id, _ = offer
    await force_status(api_db, thread_id, "needs_review", event="needs_review")
    terms = NegotiationTerms(videos=3, stance="counter", source="in_app", confidence=1.0)
    async with api_db.acquire() as conn:
        ref = await repo.load_ref(conn, thread_id)
        event_id = await repo.apply_event_id(
            conn,
            ref,
            expected={"needs_review"},
            target="countered",
            type="counter_submitted",
            actor="brand",
            payload={"resolved_review": True},
            terms=terms,
            latest_terms=terms,
            latest_terms_source="creator",
        )
    for path, body in (
        ("award/preview", None),
        ("award", award_body([], based_on=event_id)),
    ):
        r = (
            await brand_client.post(f"{THREADS}/{thread_id}/{path}")
            if body is None
            else await brand_client.post(f"{THREADS}/{thread_id}/{path}", json=body)
        )
        assert r.status_code == 422, (path, r.text)
        assert r.json()["detail"]["code"] == "terms_incomplete"
    assert (await thread_row(api_db, thread_id))["status"] == "countered"


async def test_award_not_allowed_when_awaiting(brand_client, launched_batch, offer):
    thread_id, sent_id = offer
    go_live = await go_live_of(brand_client, launched_batch.batch_id)
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/award",
        json=award_body(milestones([33333, 33333, 33334], go_live), based_on=sent_id),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "action_not_allowed"
    preview = await brand_client.post(f"{THREADS}/{thread_id}/award/preview")
    assert preview.status_code == 409


async def test_double_award_creates_one_deal(brand_client, launched_batch, countered, api_db):
    thread_id, counter_id = countered
    go_live = await go_live_of(brand_client, launched_batch.batch_id)
    body = award_body(milestones([40000] * 3, go_live), based_on=counter_id)
    first, second = await asyncio.gather(
        brand_client.post(f"{THREADS}/{thread_id}/award", json=body),
        brand_client.post(f"{THREADS}/{thread_id}/award", json=body),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409], (first.text, second.text)
    assert len((await deals_of(api_db, thread_id))[0]) == 1
    assert len(await events_of(api_db, thread_id, "awarded")) == 1
    assert (
        len([o for o in await outbox_of(api_db, thread_id) if o["kind"] == "creator_awarded"]) == 1
    )


async def test_parallel_awards_respect_target(brand_client, launched_batch, countered, api_db):
    priya, priya_counter = countered
    maya = launched_batch.threads["mayamakestech"]
    maya_counter = await force_counter(api_db, maya, 110000)
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.batches set hires_target = 1 where id = $1", launched_batch.batch_id
        )
    go_live = await go_live_of(brand_client, launched_batch.batch_id)
    first, second = await asyncio.gather(
        brand_client.post(
            f"{THREADS}/{priya}/award",
            json=award_body(milestones([40000] * 3, go_live), based_on=priya_counter),
        ),
        brand_client.post(
            f"{THREADS}/{maya}/award",
            json=award_body(milestones([36666, 36666, 36668], go_live), based_on=maya_counter),
        ),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 422], (first.text, second.text)
    refused = first if first.status_code == 422 else second
    assert refused.json()["detail"]["code"] == "over_target"
    async with api_db.acquire() as conn:
        assert (
            await conn.fetchval(
                "select count(*) from public.deals where batch_id = $1", launched_batch.batch_id
            )
            == 1
        )


async def test_award_past_target_with_confirmation(brand_client, launched_batch, countered, api_db):
    priya, priya_counter = countered
    maya = launched_batch.threads["mayamakestech"]
    maya_counter = await force_counter(api_db, maya, 110000)
    go_live = await go_live_of(brand_client, launched_batch.batch_id)
    first = await brand_client.post(
        f"{THREADS}/{priya}/award",
        json=award_body(milestones([40000] * 3, go_live), based_on=priya_counter),
    )
    assert first.status_code == 200, first.text

    preview = (await brand_client.post(f"{THREADS}/{maya}/award/preview")).json()
    assert (preview["hired"], preview["hires_target"]) == (1, 1)
    assert preview["over_target"] is True
    assert preview["would_reach_target"] is False

    body = award_body(preview["milestones"], based_on=maya_counter)
    refused = await brand_client.post(f"{THREADS}/{maya}/award", json=body)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "over_target"
    assert (await thread_row(api_db, maya))["status"] == "countered"

    confirmed = await brand_client.post(
        f"{THREADS}/{maya}/award", json=body | {"confirm_over_target": True}
    )
    assert confirmed.status_code == 200, confirmed.text
    view = (await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")).json()
    assert view["kpis"]["hired"] == 2


async def test_stale_award_409(brand_client, creator_client, launched_batch, countered, api_db):
    thread_id, counter_id = countered
    revised = await creator_client.post(
        f"{OFFERS}/{thread_id}/counter",
        json={
            "terms": {"videos": 3, "price_cents": 115000},
            "based_on_event_id": counter_id,
            "confirm_below_floor": True,
        },
    )
    assert revised.status_code == 200, revised.text
    go_live = await go_live_of(brand_client, launched_batch.batch_id)
    r = await brand_client.post(
        f"{THREADS}/{thread_id}/award",
        json=award_body(milestones([40000] * 3, go_live), based_on=counter_id),
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "terms_changed"
    assert detail["terms_event_id"] == revised.json()["terms_event_id"]
    assert (await deals_of(api_db, thread_id))[0] == []


async def test_award_other_brand_404_and_creator_403(
    new_brand_client, creator_client, launched_batch, countered
):
    thread_id, counter_id = countered
    go_live = datetime.now(UTC).date() + timedelta(days=30)
    body = award_body(milestones([40000] * 3, go_live), based_on=counter_id)
    for client, expected in ((new_brand_client, 404), (creator_client, 403)):
        for path, payload in (("award/preview", None), ("award", body)):
            r = (
                await client.post(f"{THREADS}/{thread_id}/{path}")
                if payload is None
                else await client.post(f"{THREADS}/{thread_id}/{path}", json=payload)
            )
            assert r.status_code == expected, (path, r.text)

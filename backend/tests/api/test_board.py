"""The board: batch list, batch view model with ranking and KPIs, thread detail and Retry.

Counters are set up through the thread repo (never raw UPDATEs on `thread_events`).
`launched_batch` holds every thread at `next_action_at = 'infinity'`, and workers are off in
the test environment, so nothing here can send an email or place a call.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.threads import repo
from app.schemas.negotiation import NegotiationTerms

pytestmark = pytest.mark.db

BATCHES = "/api/v1/batches"
THREADS = "/api/v1/threads"


def terms(
    price_cents: int | None = None,
    videos: int | None = 3,
    *,
    source="call",
    stance="counter",
    go_live_by=None,
) -> NegotiationTerms:
    return NegotiationTerms(
        videos=videos,
        price_cents=price_cents,
        go_live_by=go_live_by,
        stance=stance,
        source=source,
        confidence=0.9,
    )


async def ref_of(api_db, thread_id):
    async with api_db.acquire() as conn:
        return await repo.load_ref(conn, thread_id)


async def counter(api_db, thread_id, price_cents: int, *, videos: int = 3) -> None:
    """queued -> calling -> countered, with a `call_ended` event carrying the creator's terms."""
    t = terms(price_cents, videos)
    async with api_db.acquire() as conn:
        ref = await repo.load_ref(conn, thread_id)
        await repo.transition(conn, thread_id, expected={"queued"}, target="calling")
        await repo.apply_event(
            conn,
            ref,
            expected={"calling"},
            target="countered",
            type="call_ended",
            actor="creator",
            terms=t,
            latest_terms=t,
            latest_terms_source="creator",
        )


async def thread_row(api_db, thread_id):
    async with api_db.acquire() as conn:
        return await conn.fetchrow(
            "select status, attempts, last_error, call_conversation_id, next_action_at"
            " from public.threads where id = $1",
            thread_id,
        )


async def test_batch_view_shape_and_kpis(brand_client, launched_batch):
    r = await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["id"] == str(launched_batch.batch_id)
    assert len(view["threads"]) == 3
    assert {t["status"] for t in view["threads"]} == {"queued"}
    assert {t["creator"]["handle"] for t in view["threads"]} == {
        "priyareviews",
        "arjuntech",
        "mayamakestech",
    }
    kpis = view["kpis"]
    assert (kpis["contacted"], kpis["replied"], kpis["countered"]) == (0, 0, 0)
    assert kpis["best_per_video_cents"] is None
    brief = view["brief"]
    assert brief["brief_id"] == str(launched_batch.brief_id)
    assert brief["budget_ceiling_cents"] == 123400
    assert brief["ask_price_cents"] == 100000
    assert brief["deliverables_count"] == 3
    assert brief["follow_up_policy"] == "off"
    card = view["threads"][0]
    assert card["delta"]["ask_videos"] == 3
    assert card["package"]["name"]
    assert card["creator"]["initials"]
    assert card["best_value"]["eligible"] is False
    assert card["last_event"]["type"] == "queued"
    assert card["email"] is None
    assert card["live_offers"] == []


async def test_cards_ranked_after_counters(brand_client, api_db, launched_batch):
    await counter(api_db, launched_batch.threads["priyareviews"], 110000)
    await counter(api_db, launched_batch.threads["arjuntech"], 120000)

    r = await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")
    assert r.status_code == 200, r.text
    view = r.json()
    first, second, third = view["threads"]
    assert first["id"] == str(launched_batch.threads["priyareviews"])
    assert first["best_value"]["rank"] == 1
    assert "Lowest $/video" in first["best_value"]["reasons"]
    assert first["best_value"]["per_video_cents"] == 36667
    assert first["latest_terms_source"] == "creator"
    assert first["latest_terms"]["price_cents"] == 110000
    assert first["delta"]["latest_price_cents"] == 110000
    assert second["id"] == str(launched_batch.threads["arjuntech"])
    assert second["best_value"]["rank"] == 2
    assert third["best_value"]["eligible"] is False
    assert view["kpis"]["best_per_video_cents"] == 36667
    assert view["kpis"]["countered"] == 2
    assert view["kpis"]["replied"] == 2


async def test_email_preview_and_delivery_flag(brand_client, api_db, launched_batch):
    maya = launched_batch.threads["mayamakestech"]
    ref = await ref_of(api_db, maya)
    async with api_db.acquire() as conn:
        await repo.transition(conn, maya, expected={"queued"}, target="drafting")
        await repo.record_event(
            conn,
            ref,
            type="email_drafted",
            actor="system",
            payload={"attempt": 0, "subject": "Lumen Pods x Maya", "body_text": "Hi Maya"},
        )
        await repo.apply_event(
            conn,
            ref,
            expected={"drafting"},
            target="awaiting_reply",
            type="email_sent",
            actor="system",
            payload={"delivered": False},
        )

    r = await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")
    cards = {t["creator"]["handle"]: t for t in r.json()["threads"]}
    assert cards["mayamakestech"]["email"] == {
        "subject": "Lumen Pods x Maya",
        "body_text": "Hi Maya",
        "delivered": False,
    }
    assert cards["mayamakestech"]["status"] == "awaiting_reply"
    assert cards["priyareviews"]["email"] is None
    assert r.json()["kpis"]["contacted"] == 1


async def test_live_offers_listed(brand_client, api_db, launched_batch):
    arjun = launched_batch.threads["arjuntech"]
    ref = await ref_of(api_db, arjun)
    async with api_db.acquire() as conn:
        await repo.transition(conn, arjun, expected={"queued"}, target="calling")
        await repo.apply_event(
            conn, ref, expected={"calling"}, target="in_call", type="call_started", actor="system"
        )
        for price in (130000, 120000):
            await repo.record_event(
                conn,
                ref,
                type="call_offer_logged",
                actor="creator",
                payload={"speaker": "creator"},
                terms=terms(price),
            )

    r = await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")
    card = next(t for t in r.json()["threads"] if t["id"] == str(arjun))
    assert [o["price_cents"] for o in card["live_offers"]] == [130000, 120000]
    assert card["last_event"]["type"] == "call_offer_logged"
    assert r.json()["kpis"]["contacted"] == 1


async def test_thread_detail_events_and_transcripts(brand_client, api_db, launched_batch):
    arjun = launched_batch.threads["arjuntech"]
    await counter(api_db, arjun, 120000)
    async with api_db.acquire() as conn:
        older = await conn.fetchval(
            "insert into public.transcripts (thread_id, kind, external_id, turns, summary)"
            " values ($1, 'call', 'board-test-1', $2::jsonb, 'First') returning id",
            arjun,
            json.dumps([{"role": "agent", "text": "Hello", "t": 0.0}]),
        )
        await conn.execute(
            "insert into public.transcripts (thread_id, kind, external_id, turns, summary,"
            " created_at) values ($1, 'call', 'board-test-2', '[]'::jsonb, 'Second', $2)",
            arjun,
            datetime.now(UTC) + timedelta(minutes=1),
        )

    r = await brand_client.get(f"{THREADS}/{arjun}")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["card"]["id"] == str(arjun)
    ids = [e["id"] for e in detail["events"]]
    assert ids == sorted(ids) and len(ids) == 2
    assert [e["type"] for e in detail["events"]] == ["queued", "call_ended"]
    assert detail["events"][1]["terms"]["price_cents"] == 120000
    assert [t["summary"] for t in detail["transcripts"]] == ["Second", "First"]
    first = detail["transcripts"][1]
    assert first["id"] == str(older)
    assert first["turns"] == [{"role": "agent", "text": "Hello", "t": 0.0}]
    assert first["kind"] == "call"


async def test_retry_failed_requeues(brand_client, api_db, launched_batch):
    arjun = launched_batch.threads["arjuntech"]
    ref = await ref_of(api_db, arjun)
    async with api_db.acquire() as conn:
        await repo.transition(conn, arjun, expected={"queued"}, target="calling")
        await repo.set_call_conversation(conn, arjun, "conv_board_retry")
        await repo.apply_event(
            conn,
            ref,
            expected={"calling"},
            target="failed",
            type="failed",
            actor="system",
            payload={"reason": "No answer"},
            last_error="No answer",
        )

    try:
        r = await brand_client.post(f"{THREADS}/{arjun}/retry")
        assert r.status_code == 200, r.text
        assert r.json()["id"] == str(arjun)
        assert r.json()["status"] == "queued"
        assert r.json()["last_error"] is None
        row = await thread_row(api_db, arjun)
        assert row["status"] == "queued"
        assert row["attempts"] == 1
        assert row["last_error"] is None
        assert row["call_conversation_id"] is None
        assert row["next_action_at"] is None
        async with api_db.acquire() as conn:
            event = await conn.fetchrow(
                "select actor from public.thread_events where thread_id = $1 and type = 'retried'",
                arjun,
            )
        assert event["actor"] == "brand"
    finally:
        # Keep a dev worker from claiming the call thread and dialing a real person.
        async with api_db.acquire() as conn:
            await conn.execute(
                "update public.threads set next_action_at = 'infinity' where id = $1", arjun
            )


async def test_retry_non_failed_409(brand_client, api_db, launched_batch):
    maya = launched_batch.threads["mayamakestech"]
    r = await brand_client.post(f"{THREADS}/{maya}/retry")
    assert r.status_code == 409
    assert r.json()["detail"] == "thread_not_failed"
    row = await thread_row(api_db, maya)
    assert (row["status"], row["attempts"]) == ("queued", 0)
    async with api_db.acquire() as conn:
        count = await conn.fetchval(
            "select count(*) from public.thread_events where thread_id = $1 and type = 'retried'",
            maya,
        )
    assert count == 0


async def test_unknown_ids_404(brand_client):
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await brand_client.get(f"{BATCHES}/{missing}")).json()["detail"] == "batch_not_found"
    assert (await brand_client.get(f"{THREADS}/{missing}")).json()["detail"] == "thread_not_found"
    retry = await brand_client.post(f"{THREADS}/{missing}/retry")
    assert (retry.status_code, retry.json()["detail"]) == (404, "thread_not_found")


async def test_other_brand_404(new_brand_client, launched_batch):
    thread = launched_batch.threads["priyareviews"]
    responses = [
        await new_brand_client.get(f"{BATCHES}/{launched_batch.batch_id}"),
        await new_brand_client.get(f"{THREADS}/{thread}"),
        await new_brand_client.post(f"{THREADS}/{thread}/retry"),
    ]
    assert [r.status_code for r in responses] == [404, 404, 404]
    listing = await new_brand_client.get(BATCHES)
    assert listing.status_code == 200
    assert listing.json() == []


async def test_creator_403(creator_client, launched_batch):
    thread = launched_batch.threads["priyareviews"]
    responses = [
        await creator_client.get(BATCHES),
        await creator_client.get(f"{BATCHES}/{launched_batch.batch_id}"),
        await creator_client.get(f"{THREADS}/{thread}"),
        await creator_client.post(f"{THREADS}/{thread}/retry"),
    ]
    assert [r.status_code for r in responses] == [403] * 4
    assert {r.json()["detail"] for r in responses} == {"wrong_role"}


async def test_board_never_exposes_contact_or_floor(brand_client, api_db, launched_batch):
    await counter(api_db, launched_batch.threads["priyareviews"], 110000)
    async with api_db.acquire() as conn:
        creators = await conn.fetch(
            "select c.email, c.phone from public.creators c join public.threads t"
            " on t.creator_id = c.id where t.batch_id = $1",
            launched_batch.batch_id,
        )
        floors = await conn.fetch(
            "select f.floor_price_cents from public.package_floors f join public.threads t"
            " on t.package_id = f.package_id where t.batch_id = $1",
            launched_batch.batch_id,
        )
    bodies = [
        (await brand_client.get(BATCHES)).text,
        (await brand_client.get(f"{BATCHES}/{launched_batch.batch_id}")).text,
    ]
    for thread_id in launched_batch.threads.values():
        bodies.append((await brand_client.get(f"{THREADS}/{thread_id}")).text)
    secrets = [c["email"] for c in creators if c["email"]]
    secrets += [c["phone"] for c in creators if c["phone"]]
    assert secrets, "the seeded creators have contact details to look for"
    for body in bodies:
        assert "floor_price" not in body
        # `email` is also the card's EmailPreview key, so contact details are looked for by value.
        assert '"phone"' not in body
        for secret in secrets:
            assert secret not in body
    for floor in floors:
        # A floor value may coincide with a price by chance; the field name check above is
        # the guarantee, this guards against the raw number sitting next to a floor label.
        assert f'"floor_price_cents": {floor["floor_price_cents"]}' not in bodies[1]


async def test_list_batches_newest_first(brand_client, api_db, launched_batch):
    await counter(api_db, launched_batch.threads["priyareviews"], 110000)
    r = await brand_client.get(BATCHES)
    assert r.status_code == 200, r.text
    items = r.json()
    launched = [i["launched_at"] for i in items]
    assert launched == sorted(launched, reverse=True)
    mine = next(i for i in items if i["id"] == str(launched_batch.batch_id))
    assert mine["brief_id"] == str(launched_batch.brief_id)
    assert mine["product_name"]
    assert mine["thread_count"] == 3
    assert (mine["contacted"], mine["replied"], mine["countered"]) == (0, 1, 1)

"""The thread event log: idempotent appends and conditional status transitions."""

import json
import uuid

import pytest

from app.core.thread_state import IllegalTransition
from app.modules.threads import repo
from app.modules.threads.repo import StaleThread
from app.schemas.negotiation import NegotiationTerms

pytestmark = pytest.mark.db


def terms(price_cents: int = 90_000) -> NegotiationTerms:
    return NegotiationTerms(
        price_cents=price_cents, stance="counter", source="call", confidence=0.9
    )


async def make_thread(factory, *, status: str = "queued") -> repo.ThreadRef:
    brand = await factory.brand()
    creator = await factory.creator()
    package_id = await factory.package(creator.id)
    brief_id = await factory.brief(brand)
    batch_id = await factory.batch(brief_id, brand)
    thread_id = await factory.thread(batch_id, brand, creator, package_id, status=status)
    return repo.ThreadRef(id=thread_id, batch_id=batch_id, brand_id=brand.id, creator_id=creator.id)


async def status_of(conn, thread: repo.ThreadRef) -> str:
    return await conn.fetchval("select status from public.threads where id = $1", thread.id)


async def event_count(conn, thread: repo.ThreadRef) -> int:
    return await conn.fetchval(
        "select count(*) from public.thread_events where thread_id = $1", thread.id
    )


async def test_load_ref_returns_ids_or_none(db_conn, factory):
    thread = await make_thread(factory)

    assert await repo.load_ref(db_conn, thread.id) == thread
    assert await repo.load_ref(db_conn, uuid.UUID(int=0)) is None


async def test_record_event_returns_id_and_stores_terms(db_conn, factory):
    thread = await make_thread(factory)

    event_id = await repo.record_event(
        db_conn,
        thread,
        type="call_offer_logged",
        actor="brand_agent",
        payload={"note": "hi"},
        terms=terms(),
    )

    assert isinstance(event_id, int)
    row = await db_conn.fetchrow(
        "select batch_id, brand_id, creator_id, type, actor, payload, terms"
        " from public.thread_events where id = $1",
        event_id,
    )
    assert (row["batch_id"], row["brand_id"], row["creator_id"]) == (
        thread.batch_id,
        thread.brand_id,
        thread.creator_id,
    )
    assert (row["type"], row["actor"]) == ("call_offer_logged", "brand_agent")
    assert json.loads(row["payload"]) == {"note": "hi"}
    assert json.loads(row["terms"]) == terms().model_dump(mode="json")


async def test_duplicate_external_id_returns_none(db_conn, factory):
    thread = await make_thread(factory)
    first = await repo.record_event(
        db_conn, thread, type="call_ended", actor="system", external_id="conv-1"
    )
    again = await repo.record_event(
        db_conn, thread, type="call_ended", actor="system", external_id="conv-1"
    )

    assert first is not None
    assert again is None
    assert await event_count(db_conn, thread) == 1


async def test_transition_moves_status(db_conn, factory):
    thread = await make_thread(factory)

    await repo.transition(db_conn, thread.id, expected={"queued"}, target="drafting")

    assert await status_of(db_conn, thread) == "drafting"


async def test_transition_from_unexpected_status_raises_stale(db_conn, factory):
    thread = await make_thread(factory)  # queued

    with pytest.raises(StaleThread):
        await repo.transition(db_conn, thread.id, expected={"calling"}, target="in_call")

    assert await status_of(db_conn, thread) == "queued"


async def test_illegal_transition_raises_before_sql(db_conn, factory):
    thread = await make_thread(factory, status="declined")

    with pytest.raises(IllegalTransition):
        await repo.transition(db_conn, thread.id, expected={"declined"}, target="queued")

    assert await status_of(db_conn, thread) == "declined"


async def test_apply_event_rolls_back_event_when_stale(db_conn, factory):
    thread = await make_thread(factory)  # queued

    with pytest.raises(StaleThread):
        await repo.apply_event(
            db_conn,
            thread,
            expected={"calling"},
            target="in_call",
            type="call_started",
            actor="system",
        )

    assert await event_count(db_conn, thread) == 0
    assert await status_of(db_conn, thread) == "queued"


async def test_apply_event_records_and_transitions(db_conn, factory):
    thread = await make_thread(factory)

    applied = await repo.apply_event(
        db_conn,
        thread,
        expected={"queued"},
        target="drafting",
        type="queued",
        actor="system",
        external_id="k1",
    )

    assert applied is True
    assert await event_count(db_conn, thread) == 1
    assert await status_of(db_conn, thread) == "drafting"


async def test_apply_event_duplicate_does_not_transition(db_conn, factory):
    thread = await make_thread(factory)
    await factory.event(thread.id, "failed", external_id="dup")

    applied = await repo.apply_event(
        db_conn,
        thread,
        expected={"queued"},
        target="failed",
        type="failed",
        actor="system",
        external_id="dup",
        last_error="boom",
    )

    assert applied is False
    assert await status_of(db_conn, thread) == "queued"
    assert await event_count(db_conn, thread) == 1


async def test_apply_event_without_target_only_records(db_conn, factory):
    thread = await make_thread(factory)

    applied = await repo.apply_event(
        db_conn, thread, expected={"queued"}, target=None, type="email_drafted", actor="system"
    )

    assert applied is True
    assert await status_of(db_conn, thread) == "queued"
    assert await event_count(db_conn, thread) == 1


async def test_latest_terms_kept_when_not_given(db_conn, factory):
    thread = await make_thread(factory)
    await repo.update_latest_terms(db_conn, thread.id, terms(), "creator")

    await repo.transition(
        db_conn, thread.id, expected={"queued"}, target="failed", last_error="no luck"
    )

    row = await db_conn.fetchrow(
        "select status, last_error, latest_terms, latest_terms_source"
        " from public.threads where id = $1",
        thread.id,
    )
    assert row["status"] == "failed"
    assert row["last_error"] == "no luck"
    assert json.loads(row["latest_terms"]) == terms().model_dump(mode="json")
    assert row["latest_terms_source"] == "creator"


async def test_transition_sets_latest_terms(db_conn, factory):
    thread = await make_thread(factory, status="calling")

    await repo.transition(
        db_conn,
        thread.id,
        expected={"calling"},
        target="countered",
        latest_terms=terms(80_000),
        latest_terms_source="creator",
    )

    row = await db_conn.fetchrow(
        "select latest_terms, latest_terms_source from public.threads where id = $1", thread.id
    )
    assert json.loads(row["latest_terms"])["price_cents"] == 80_000
    assert row["latest_terms_source"] == "creator"


async def expires_at_of(conn, thread: repo.ThreadRef):
    return await conn.fetchval("select expires_at from public.threads where id = $1", thread.id)


async def test_awaiting_reply_sets_expiry(db_conn, factory):
    thread = await make_thread(factory, status="drafting")
    await db_conn.execute(
        "update public.batches set offer_ttl_days = 3 where id = $1", thread.batch_id
    )

    await repo.transition(db_conn, thread.id, expected={"drafting"}, target="awaiting_reply")

    drift = await db_conn.fetchval(
        "select abs(extract(epoch from expires_at - (now() + interval '3 days')))"
        " from public.threads where id = $1",
        thread.id,
    )
    assert drift is not None and drift < 5


async def test_leaving_awaiting_reply_clears_expiry(db_conn, factory):
    thread = await make_thread(factory, status="drafting")
    await repo.transition(db_conn, thread.id, expected={"drafting"}, target="awaiting_reply")
    assert await expires_at_of(db_conn, thread) is not None

    await repo.transition(db_conn, thread.id, expected={"awaiting_reply"}, target="failed")

    assert await expires_at_of(db_conn, thread) is None


async def test_apply_event_id_returns_id_then_none(db_conn, factory):
    thread = await make_thread(factory)

    first = await repo.apply_event_id(
        db_conn,
        thread,
        expected={"queued"},
        target="drafting",
        type="queued",
        actor="system",
        external_id="k-id",
    )
    again = await repo.apply_event_id(
        db_conn,
        thread,
        expected={"drafting"},
        target="failed",
        type="queued",
        actor="system",
        external_id="k-id",
    )

    assert isinstance(first, int)
    assert again is None
    assert await status_of(db_conn, thread) == "drafting"
    assert await event_count(db_conn, thread) == 1


async def test_latest_terms_event_id_ignores_non_terms(db_conn, factory):
    thread = await make_thread(factory)
    terms_event = await factory.event(thread.id, "email_sent")
    await factory.event(thread.id, "call_placed")

    assert await repo.latest_terms_event_id(db_conn, thread.id) == terms_event


async def test_latest_terms_event_id_none_without_terms_events(db_conn, factory):
    thread = await make_thread(factory)
    await factory.event(thread.id, "call_placed")

    assert await repo.latest_terms_event_id(db_conn, thread.id) is None


async def test_assert_fresh_passes_and_returns_status(db_conn, factory):
    thread = await make_thread(factory, status="awaiting_reply")
    sent = await factory.event(thread.id, "email_sent")

    async with db_conn.transaction():
        assert await repo.assert_fresh(db_conn, thread.id, sent) == "awaiting_reply"


async def test_assert_fresh_raises_on_newer_terms(db_conn, factory):
    thread = await make_thread(factory, status="awaiting_reply")
    sent = await factory.event(thread.id, "email_sent")
    newer = await factory.event(thread.id, "counter_submitted", actor="creator")

    with pytest.raises(repo.TermsChanged) as caught:
        async with db_conn.transaction():
            await repo.assert_fresh(db_conn, thread.id, sent)

    assert caught.value.latest_event_id == newer


async def test_assert_fresh_none_when_no_terms_yet(db_conn, factory):
    thread = await make_thread(factory)  # queued

    async with db_conn.transaction():
        assert await repo.assert_fresh(db_conn, thread.id, None) == "queued"


async def test_assert_fresh_raises_when_terms_exist_but_caller_saw_none(db_conn, factory):
    thread = await make_thread(factory)
    newer = await factory.event(thread.id, "email_sent")

    with pytest.raises(repo.TermsChanged) as caught:
        async with db_conn.transaction():
            await repo.assert_fresh(db_conn, thread.id, None)

    assert caught.value.latest_event_id == newer


async def test_latest_brand_counter(db_conn, factory):
    thread = await make_thread(factory, status="awaiting_reply")
    for price in (80_000, 95_000):
        await repo.record_event(
            db_conn,
            thread,
            type="brand_counter_sent",
            actor="brand",
            terms=NegotiationTerms(
                videos=3, price_cents=price, stance="counter", source="in_app", confidence=1.0
            ),
        )
    await repo.record_event(
        db_conn, thread, type="counter_submitted", actor="creator", terms=terms(120_000)
    )

    latest = await repo.latest_brand_counter(db_conn, thread.id)

    assert latest is not None
    assert (latest.videos, latest.price_cents) == (3, 95_000)


async def test_latest_brand_counter_none_without_one(db_conn, factory):
    thread = await make_thread(factory)

    assert await repo.latest_brand_counter(db_conn, thread.id) is None

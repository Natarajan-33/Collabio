"""Helpers shared by the API tests of the deal loop (offers, board actions, deals)."""

import json

from app.adapters.db import Database
from app.modules.threads import repo
from app.schemas.negotiation import NegotiationTerms


async def send_held(api_db: Database, thread_id) -> int:
    """Move a held thread `queued -> drafting -> awaiting_reply`, as an outreach send would
    without sending anything, and return the id of its `email_sent` event (the brand's ask)."""
    async with api_db.acquire() as conn:
        ref = await repo.load_ref(conn, thread_id)
        assert ref is not None
        await repo.transition(conn, thread_id, expected={"queued"}, target="drafting")
        event_id = await repo.apply_event_id(
            conn,
            ref,
            expected={"drafting"},
            target="awaiting_reply",
            type="email_sent",
            actor="system",
            payload={"delivered": False},
        )
    assert event_id is not None
    return event_id


async def record_brand_counter(
    api_db: Database,
    thread_id,
    price_cents: int,
    *,
    videos: int = 3,
    note: str | None = None,
) -> int:
    """Record a `brand_counter_sent` event on an offer that stays `awaiting_reply`, and make it
    the thread's latest terms (source brand). Returns the event id."""
    terms = NegotiationTerms(
        videos=videos,
        format="short_video",
        price_cents=price_cents,
        stance="offer",
        source="in_app",
        confidence=1.0,
    )
    async with api_db.acquire() as conn:
        ref = await repo.load_ref(conn, thread_id)
        assert ref is not None
        event_id = await repo.apply_event_id(
            conn,
            ref,
            expected={"awaiting_reply"},
            target=None,
            type="brand_counter_sent",
            actor="brand",
            payload={"note": note} if note else {},
            terms=terms,
        )
        assert event_id is not None
        await repo.update_latest_terms(conn, thread_id, terms, "brand")
    return event_id


async def events_of(api_db: Database, thread_id, type_: str | None = None) -> list[dict]:
    """The thread's events, oldest first, with `payload` and `terms` decoded."""
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select id, type, actor, payload, terms from public.thread_events"
            " where thread_id = $1 and ($2::text is null or type = $2) order by id",
            thread_id,
            type_,
        )
    return [
        dict(r) | {"payload": json.loads(r["payload"]), "terms": json.loads(r["terms"] or "null")}
        for r in rows
    ]


async def outbox_of(api_db: Database, thread_id) -> list[dict]:
    """The thread's outbox rows, oldest first, with `payload` decoded."""
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select kind, event_id, payload from public.outbox_emails where thread_id = $1"
            " order by id",
            thread_id,
        )
    return [dict(r) | {"payload": json.loads(r["payload"])} for r in rows]


async def thread_row(api_db: Database, thread_id):
    """The thread's status, expiry and latest terms."""
    async with api_db.acquire() as conn:
        return await conn.fetchrow(
            "select status, expires_at, latest_terms, latest_terms_source"
            " from public.threads where id = $1",
            thread_id,
        )


async def force_status(
    api_db: Database,
    thread_id,
    target: str | None,
    *,
    event: str,
    actor: str = "system",
    payload=None,
) -> int:
    """Record one `event`, move the thread to `target` (None: leave its status) and return the
    event's id.

    For tests that need a thread in a status no endpoint reaches (`needs_review`, `awarded`
    without a deal); the state machine still has to allow the move.
    """
    async with api_db.acquire() as conn:
        ref = await repo.load_ref(conn, thread_id)
        assert ref is not None
        current = await conn.fetchval("select status from public.threads where id = $1", thread_id)
        event_id = await repo.apply_event_id(
            conn,
            ref,
            expected={current},
            target=target,
            type=event,  # type: ignore[arg-type]
            actor=actor,  # type: ignore[arg-type]
            payload=payload,
        )
    assert event_id is not None
    return event_id

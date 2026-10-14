"""Helpers shared by the API tests of the deal loop (offers, board actions, deals)."""

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

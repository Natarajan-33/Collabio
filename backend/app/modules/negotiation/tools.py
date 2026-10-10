"""The negotiation agent's server tools: `check_counter` and `log_offer`.

`check_counter_tool` is the one place (besides the board's ranking) that reads the brand's private
budget ceiling. Its result hints at the ceiling (the first suggestion is the midpoint of ask and
ceiling), so nothing it computes is stored or logged: the only write is the over-budget count.
"""

from datetime import date
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.core.guardrails import check_counter
from app.modules.threads import repo
from app.schemas.negotiation import (
    CheckCounterRequest,
    CheckCounterResponse,
    LogOfferRequest,
    LogOfferResponse,
    NegotiationTerms,
)

# Locks the thread so concurrent tool calls serialize the concessions counter.
LOCK_THREAD = """
select status, batch_id, concessions from public.threads where id = $1 for update
"""
SELECT_BRIEF_LIMITS = """
select b.budget_ceiling_cents, b.ask_price_cents, b.deliverables_count, b.brand_name
from public.batches ba join public.briefs b on b.id = ba.brief_id
where ba.id = $1
"""
BUMP_CONCESSIONS = "update public.threads set concessions = concessions + 1 where id = $1"
CALL_STATUSES = ("calling", "in_call")  # Ruling 5: the watcher can lag the first tool call


class ThreadNotFound(Exception):
    """No thread has this id."""


class ThreadNotInCall(Exception):
    """The thread is not in a call (`calling` or `in_call`)."""


async def _lock_call_thread(conn: asyncpg.Connection, thread_id: UUID) -> asyncpg.Record:
    row = await conn.fetchrow(LOCK_THREAD, thread_id)
    if row is None:
        raise ThreadNotFound(str(thread_id))
    if row["status"] not in CALL_STATUSES:
        raise ThreadNotInCall(str(thread_id))
    return row


async def check_counter_tool(db: Database, req: CheckCounterRequest) -> CheckCounterResponse:
    """Judge the creator's price against the private ceiling. Records no event (Ruling 4)."""
    async with db.transaction() as conn:
        thread = await _lock_call_thread(conn, req.thread_id)
        brief = await conn.fetchrow(SELECT_BRIEF_LIMITS, thread["batch_id"])
        verdict = check_counter(
            ceiling_cents=brief["budget_ceiling_cents"],
            ask_cents=brief["ask_price_cents"],
            brief_videos=brief["deliverables_count"],
            offered_price_cents=round(req.price_usd * 100),
            offered_videos=req.videos,
            concessions_made=thread["concessions"],
            brand_name=brief["brand_name"],
        )
        if verdict.verdict == "over":
            await conn.execute(BUMP_CONCESSIONS, req.thread_id)
    suggested = verdict.suggested_counter_price_cents
    return CheckCounterResponse(
        verdict=verdict.verdict,
        suggested_counter_price_usd=None if suggested is None else suggested // 100,
        talking_point=verdict.talking_point,
    )


def _parse_date(value: str) -> date | None:
    """The agent's `go_live_by` when it is an ISO date, else None ("next friday" is dropped)."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


async def log_offer_tool(db: Database, req: LogOfferRequest) -> LogOfferResponse:
    """Record an offer said on the call and make it the thread's latest terms."""
    creator_spoke = req.speaker == "creator"
    terms = NegotiationTerms(
        videos=req.videos,
        # A sub-cent price rounds to 0, which is no price.
        price_cents=(round(req.price_usd * 100) or None) if req.price_usd else None,
        go_live_by=_parse_date(req.go_live_by),
        conditions=[part.strip() for part in req.conditions.split(",") if part.strip()],
        stance=req.stance,
        source="call",
        confidence=0.9,
    )
    async with db.transaction() as conn:
        await _lock_call_thread(conn, req.thread_id)
        thread = await repo.load_ref(conn, req.thread_id)
        await repo.record_event(
            conn,
            thread,
            type="call_offer_logged",
            actor="creator" if creator_spoke else "brand_agent",
            payload={"speaker": req.speaker},
            terms=terms,
        )
        if terms.price_cents is not None or terms.videos is not None:
            await repo.update_latest_terms(
                conn, req.thread_id, terms, "creator" if creator_spoke else "brand"
            )
    return LogOfferResponse(logged=True)

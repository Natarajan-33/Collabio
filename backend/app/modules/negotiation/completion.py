"""Finishing a call: the transcript, the structured terms and the thread's next status.

Two doors lead here, the signed post-call webhook and the call watcher, and either may deliver
the same conversation more than once. What makes that safe:

- A transcript is unique per `(kind, external_id)` and `call_ended` per `(type, external_id)`,
  both written in one transaction with the status change, so a conversation completes once
  however many deliveries arrive.
- The read-only checks run before the Gemini call, so a delivery that arrives after the first
  one committed never reaches Gemini.
- Deliveries that overlap inside one process queue behind a per-conversation lock, so the
  later ones see the committed result and skip Gemini too. Across processes two overlapping
  deliveries may both call Gemini; the second still loses at the insert.

Nothing here reads or stores the brand's budget ceiling: the structurer is told the ask, the
transcript and the offers logged on the call, nothing else (spec 6.2).
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.adapters.elevenlabs import ConversationSnapshot
from app.adapters.gemini import GeminiPort
from app.core.package_text import package_one_liner
from app.core.thread_state import status_after_call
from app.modules.negotiation.calls import load_call_context
from app.modules.negotiation.prompts import CallAsk
from app.modules.negotiation.structurer import structure_call
from app.modules.threads import repo
from app.modules.threads.repo import StaleThread, ThreadRef
from app.schemas.negotiation import NegotiationTerms

logger = logging.getLogger(__name__)

CALL_STATUSES = {"calling", "in_call"}
NO_ANSWER = "No answer."
LOW_CONFIDENCE = "Low confidence in the call terms."
UNREADABLE = "Couldn't read the call terms."

SELECT_CALL_THREAD = """
select id, batch_id, brand_id, creator_id, status
from public.threads where call_conversation_id = $1
"""
CALL_ENDED_EXISTS = """
select exists (
  select 1 from public.thread_events where type = 'call_ended' and external_id = $1
)
"""
SELECT_ASK_FORMAT = """
select b.deliverables_format
from public.threads t
join public.batches ba on ba.id = t.batch_id
join public.briefs b on b.id = ba.brief_id
where t.id = $1
"""
SELECT_LOGGED_OFFERS = """
select terms from public.thread_events
where thread_id = $1 and type = 'call_offer_logged' and terms is not null
order by id
"""
INSERT_CALL_TRANSCRIPT = """
insert into public.transcripts (thread_id, kind, external_id, turns, summary)
values ($1, 'call', $2, $3::jsonb, $4)
on conflict (kind, external_id) do nothing
returning id
"""
SELECT_INTAKE_BRIEF = """
select id from public.briefs
where intake_conversation_id = $1
   or ($2::uuid is not null and id = $2::uuid
       and (intake_conversation_id is null or intake_conversation_id = $1))
order by (intake_conversation_id = $1) desc nulls last
limit 1
"""
INSERT_INTAKE_TRANSCRIPT = """
insert into public.transcripts (brief_id, kind, external_id, turns, summary)
values ($1, 'intake', $2, $3::jsonb, $4)
on conflict (kind, external_id) do nothing
returning id
"""

_waiters: dict[str, tuple[asyncio.Lock, int]] = {}


@asynccontextmanager
async def _one_at_a_time(key: str) -> AsyncIterator[None]:
    """Serialise work on `key` within this process; the entry is dropped when nobody uses it."""
    lock, users = _waiters.get(key) or (asyncio.Lock(), 0)
    _waiters[key] = (lock, users + 1)
    try:
        async with lock:
            yield
    finally:
        lock, users = _waiters[key]
        if users == 1:
            del _waiters[key]
        else:
            _waiters[key] = (lock, users - 1)


def _turns_json(snapshot: ConversationSnapshot) -> str:
    return json.dumps([turn.model_dump(mode="json") for turn in snapshot.turns])


async def _load_ask(conn: asyncpg.Connection, thread_id: UUID) -> CallAsk:
    ctx = await load_call_context(conn, thread_id)
    return CallAsk(
        videos=ctx.ask_videos,
        price_cents=ctx.ask_price_cents,
        go_live_by=ctx.go_live_by,
        format=await conn.fetchval(SELECT_ASK_FORMAT, thread_id),
        package_one_liner=package_one_liner(ctx.package),
    )


async def _load_logged(conn: asyncpg.Connection, thread_id: UUID) -> list[NegotiationTerms]:
    rows = await conn.fetch(SELECT_LOGGED_OFFERS, thread_id)
    return [NegotiationTerms.model_validate_json(row["terms"]) for row in rows]


async def complete_call(
    db: Database, gemini: GeminiPort | None, conversation_id: str, snapshot: ConversationSnapshot
) -> bool:
    """Finish the call on `conversation_id`. True when this delivery completed it; False when
    there is no such call, it already finished, or the thread moved on."""
    async with _one_at_a_time(conversation_id):
        return await _complete_call(db, gemini, conversation_id, snapshot)


async def _complete_call(
    db: Database, gemini: GeminiPort | None, conversation_id: str, snapshot: ConversationSnapshot
) -> bool:
    async with db.acquire() as conn:
        row = await conn.fetchrow(SELECT_CALL_THREAD, conversation_id)
        if row is None:
            return False
        if await conn.fetchval(CALL_ENDED_EXISTS, conversation_id):
            return False
        if row["status"] not in CALL_STATUSES:
            return False
        thread = ThreadRef(
            id=row["id"],
            batch_id=row["batch_id"],
            brand_id=row["brand_id"],
            creator_id=row["creator_id"],
        )
        if snapshot.user_spoke:
            ask = await _load_ask(conn, thread.id)
            logged = await _load_logged(conn, thread.id)

    if not snapshot.user_spoke:
        # Ringing can read as in progress, so a call nobody answered reaches us as `done`.
        return await _fail_unanswered(db, thread, conversation_id)

    structured = await structure_call(gemini, ask=ask, turns=snapshot.turns, logged=logged)
    terms = structured.terms if structured else None
    summary = structured.summary if structured else snapshot.summary
    target = status_after_call(terms)
    try:
        async with db.transaction() as conn:
            transcript_id = await conn.fetchval(
                INSERT_CALL_TRANSCRIPT, thread.id, conversation_id, _turns_json(snapshot), summary
            )
            if transcript_id is None:
                return False
            has_terms = terms is not None and bool(terms.price_cents or terms.videos)
            await repo.apply_event(
                conn,
                thread,
                expected=CALL_STATUSES,
                target=target,
                type="call_ended",
                actor="system",
                payload={"summary": summary, "duration_secs": snapshot.duration_secs},
                terms=terms,
                transcript_id=transcript_id,
                external_id=conversation_id,
                latest_terms=terms if has_terms else None,
                latest_terms_source="creator" if has_terms else None,
            )
            if target == "needs_review":
                reason = UNREADABLE if terms is None else LOW_CONFIDENCE
                await repo.record_event(
                    conn, thread, type="needs_review", actor="system", payload={"reason": reason}
                )
    except StaleThread:
        return False
    return True


async def _fail_unanswered(db: Database, thread: ThreadRef, conversation_id: str) -> bool:
    try:
        async with db.acquire() as conn:
            await repo.apply_event(
                conn,
                thread,
                expected=CALL_STATUSES,
                target="failed",
                type="failed",
                actor="system",
                payload={"reason": NO_ANSWER},
                last_error=NO_ANSWER,
                external_id=conversation_id,
            )
    except StaleThread:
        logger.info("Thread %s moved before its unanswered call was failed", thread.id)
    return True


async def complete_intake(
    db: Database,
    conversation_id: str,
    snapshot: ConversationSnapshot,
    *,
    brief_id: UUID | None = None,
) -> bool:
    """Store the brief agent's conversation as an `intake` transcript on its brief. True when
    one was stored now; False when no brief owns the conversation or it was stored already."""
    async with db.transaction() as conn:
        found = await conn.fetchval(SELECT_INTAKE_BRIEF, conversation_id, brief_id)
        if found is None:
            return False
        stored = await conn.fetchval(
            INSERT_INTAKE_TRANSCRIPT,
            found,
            conversation_id,
            _turns_json(snapshot),
            snapshot.summary,
        )
    return stored is not None


async def fail_call(db: Database, conversation_id: str, reason: str) -> None:
    """Fail the `calling` thread whose call is `conversation_id`, with `reason`."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(SELECT_CALL_THREAD, conversation_id)
        if row is None or row["status"] != "calling":
            return
        thread = ThreadRef(
            id=row["id"],
            batch_id=row["batch_id"],
            brand_id=row["brand_id"],
            creator_id=row["creator_id"],
        )
        try:
            await repo.apply_event(
                conn,
                thread,
                expected={"calling"},
                target="failed",
                type="failed",
                actor="system",
                payload={"reason": reason},
                last_error=reason,
                external_id=conversation_id,
            )
        except StaleThread:
            return

"""The thread event log and conditional status transitions.

Every function takes the caller's connection and leaves the transaction to the caller.
`thread_events` is append-only, and a thread's status only changes through `transition` or
`apply_event`, in the same transaction as the event that explains it. jsonb values go in as
`json.dumps` text cast with `::jsonb`, and come back as text.
"""

import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Literal
from uuid import UUID

import asyncpg

from app.core.thread_state import IllegalTransition, check_transition
from app.schemas.negotiation import TERMS_EVENT_TYPES, Actor, EventType, NegotiationTerms

TermsSource = Literal["brand", "creator"]

SELECT_STATUS = "select status from public.threads where id = $1"

SELECT_REF = "select id, batch_id, brand_id, creator_id from public.threads where id = $1"
INSERT_EVENT = """
insert into public.thread_events
  (thread_id, batch_id, brand_id, creator_id, type, actor, payload, terms, transcript_id,
   external_id)
values ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10)
on conflict (type, external_id) do nothing
returning id
"""
UPDATE_STATUS = """
update public.threads
set status = $2,
    last_error = $3,
    latest_terms = coalesce($4::jsonb, latest_terms),
    latest_terms_source = coalesce($5, latest_terms_source),
    expires_at = case when $2 = 'awaiting_reply'
      then now() + make_interval(days => (select b.offer_ttl_days from public.batches b
                                          where b.id = threads.batch_id))
      else null end
where id = $1 and status = any($6::text[])
"""
CLAIM_QUEUED = """
with next as (
  select id from public.threads
  where status = 'queued'
    and (($2::uuid is null and (next_action_at is null or next_action_at <= now()))
         or batch_id = $2::uuid)
  order by created_at, id
  for update skip locked
  limit $1
)
update public.threads t
set status = case when t.channel_plan = 'call' then 'calling' else 'drafting' end
from next
where t.id = next.id
returning t.id, t.channel_plan, t.status
"""
COUNT_CALLS_SINCE = """
select count(*) from public.thread_events
where brand_id = $1 and type = 'call_placed' and created_at >= $2
"""
SET_CALL_CONVERSATION = """
update public.threads set call_conversation_id = $2 where id = $1
"""
SELECT_LIVE_CALLS = """
select t.id, t.batch_id, t.brand_id, t.creator_id, t.status, t.call_conversation_id
from public.threads t
where t.status in ('calling', 'in_call')
  and t.call_conversation_id is not null
  and ($1::uuid is null or t.batch_id = $1::uuid)
order by t.created_at, t.id
"""
SELECT_LATEST_TERMS_EVENT = """
select id from public.thread_events
where thread_id = $1 and type = any($2::text[])
order by id desc
limit 1
"""
SELECT_STATUS_FOR_UPDATE = "select status from public.threads where id = $1 for update"
SELECT_LATEST_BRAND_COUNTER = """
select terms from public.thread_events
where thread_id = $1 and type = 'brand_counter_sent' and terms is not null
order by id desc
limit 1
"""
UPDATE_TERMS = """
update public.threads set latest_terms = $2::jsonb, latest_terms_source = $3 where id = $1
"""


@dataclass(frozen=True)
class ThreadRef:
    id: UUID
    batch_id: UUID
    brand_id: UUID
    creator_id: UUID


@dataclass(frozen=True)
class ClaimedThread:
    id: UUID
    channel_plan: str
    status: str  # what the claim moved it to: `drafting` or `calling`


@dataclass(frozen=True)
class LiveCall:
    """A placed call that has not finished: the watcher polls its conversation."""

    thread: ThreadRef
    status: str  # `calling` (placed, not answered yet) or `in_call`
    conversation_id: str


class StaleThread(Exception):
    """The thread was not in an expected status: someone else moved it first."""


class TermsChanged(Exception):
    """The terms moved on since the caller looked: a newer terms event exists."""

    def __init__(self, latest_event_id: int | None) -> None:
        super().__init__(f"Terms changed (latest terms event {latest_event_id})")
        self.latest_event_id = latest_event_id


def _terms_json(terms: NegotiationTerms | None) -> str | None:
    return None if terms is None else json.dumps(terms.model_dump(mode="json"))


async def load_ref(conn: asyncpg.Connection, thread_id: UUID) -> ThreadRef | None:
    row = await conn.fetchrow(SELECT_REF, thread_id)
    return None if row is None else ThreadRef(**row)


async def record_event(
    conn: asyncpg.Connection,
    thread: ThreadRef,
    *,
    type: EventType,
    actor: Actor,
    payload: dict | None = None,
    terms: NegotiationTerms | None = None,
    transcript_id: UUID | None = None,
    external_id: str | None = None,
) -> int | None:
    """Append an event; returns its id, or None when `(type, external_id)` is already recorded."""
    return await conn.fetchval(
        INSERT_EVENT,
        thread.id,
        thread.batch_id,
        thread.brand_id,
        thread.creator_id,
        type,
        actor,
        json.dumps(payload or {}),
        _terms_json(terms),
        transcript_id,
        external_id,
    )


async def transition(
    conn: asyncpg.Connection,
    thread_id: UUID,
    *,
    expected: Collection[str],
    target: str,
    last_error: str | None = None,
    latest_terms: NegotiationTerms | None = None,
    latest_terms_source: TermsSource | None = None,
) -> None:
    """Move a thread to `target` if it is still in one of `expected`, else raise `StaleThread`.

    Raises `IllegalTransition` before any SQL when the state machine forbids a move from any
    expected status. `latest_terms` and its source are kept when not given; `last_error` is
    always overwritten.
    """
    for status in expected:
        check_transition(status, target)
    result = await conn.execute(
        UPDATE_STATUS,
        thread_id,
        target,
        last_error,
        _terms_json(latest_terms),
        latest_terms_source,
        list(expected),
    )
    if result != "UPDATE 1":
        raise StaleThread(f"Thread {thread_id} is not in {sorted(expected)}")


async def apply_event_id(
    conn: asyncpg.Connection,
    thread: ThreadRef,
    *,
    expected: Collection[str],
    target: str | None,
    type: EventType,
    actor: Actor,
    payload: dict | None = None,
    terms: NegotiationTerms | None = None,
    transcript_id: UUID | None = None,
    external_id: str | None = None,
    last_error: str | None = None,
    latest_terms: NegotiationTerms | None = None,
    latest_terms_source: TermsSource | None = None,
) -> int | None:
    """Record an event and, when `target` is set, move the thread, atomically.

    Returns the event's id, or None without transitioning when the event is a duplicate.
    `StaleThread` propagates and rolls the event back.
    """
    async with conn.transaction():
        event_id = await record_event(
            conn,
            thread,
            type=type,
            actor=actor,
            payload=payload,
            terms=terms,
            transcript_id=transcript_id,
            external_id=external_id,
        )
        if event_id is None:
            return None
        if target is not None:
            await transition(
                conn,
                thread.id,
                expected=expected,
                target=target,
                last_error=last_error,
                latest_terms=latest_terms,
                latest_terms_source=latest_terms_source,
            )
        return event_id


async def apply_event(
    conn: asyncpg.Connection,
    thread: ThreadRef,
    *,
    expected: Collection[str],
    target: str | None,
    type: EventType,
    actor: Actor,
    payload: dict | None = None,
    terms: NegotiationTerms | None = None,
    transcript_id: UUID | None = None,
    external_id: str | None = None,
    last_error: str | None = None,
    latest_terms: NegotiationTerms | None = None,
    latest_terms_source: TermsSource | None = None,
) -> bool:
    """`apply_event_id` for callers that only need to know whether the event was new."""
    return (
        await apply_event_id(
            conn,
            thread,
            expected=expected,
            target=target,
            type=type,
            actor=actor,
            payload=payload,
            terms=terms,
            transcript_id=transcript_id,
            external_id=external_id,
            last_error=last_error,
            latest_terms=latest_terms,
            latest_terms_source=latest_terms_source,
        )
        is not None
    )


async def latest_terms_event_id(conn: asyncpg.Connection, thread_id: UUID) -> int | None:
    """The id of the thread's newest event that carries terms, or None."""
    return await conn.fetchval(SELECT_LATEST_TERMS_EVENT, thread_id, sorted(TERMS_EVENT_TYPES))


async def assert_fresh(
    conn: asyncpg.Connection, thread_id: UUID, based_on_event_id: int | None
) -> str:
    """Lock the thread row and check the caller saw the newest terms; returns the status.

    Raises `TermsChanged` when the newest terms event is not `based_on_event_id`, and
    `LookupError` for an unknown thread. Call inside a transaction: the lock lasts until it
    ends, so the caller's own write cannot interleave with another action.
    """
    status = await conn.fetchval(SELECT_STATUS_FOR_UPDATE, thread_id)
    if status is None:
        raise LookupError(f"No thread {thread_id}")
    latest = await latest_terms_event_id(conn, thread_id)
    if latest != based_on_event_id:
        raise TermsChanged(latest)
    return status


async def latest_brand_counter(
    conn: asyncpg.Connection, thread_id: UUID
) -> NegotiationTerms | None:
    """The terms of the brand's newest `brand_counter_sent` event, or None."""
    raw = await conn.fetchval(SELECT_LATEST_BRAND_COUNTER, thread_id)
    return None if raw is None else NegotiationTerms.model_validate_json(raw)


async def update_latest_terms(
    conn: asyncpg.Connection, thread_id: UUID, terms: NegotiationTerms, source: TermsSource
) -> None:
    """Set the thread's latest terms without changing its status."""
    await conn.execute(UPDATE_TERMS, thread_id, _terms_json(terms), source)


async def fail_thread(conn: asyncpg.Connection, thread_id: UUID, reason: str) -> None:
    """Move a thread to `failed` with a `failed` event carrying `reason`.

    Does nothing when the thread's status cannot move to `failed` or someone else moves it
    first; a failure is never worth an error of its own.
    """
    thread = await load_ref(conn, thread_id)
    current = await conn.fetchval(SELECT_STATUS, thread_id)
    if thread is None or current is None:
        return
    try:
        check_transition(current, "failed")
    except IllegalTransition:
        return
    try:
        await apply_event(
            conn,
            thread,
            expected={current},
            target="failed",
            type="failed",
            actor="system",
            payload={"reason": reason},
            last_error=reason,
        )
    except StaleThread:
        return


async def claim_queued(
    conn: asyncpg.Connection, *, limit: int, batch_id: UUID | None = None
) -> list[ClaimedThread]:
    """Claim up to `limit` queued threads, oldest first, moving each to `drafting`
    (`calling` for a call).

    `FOR UPDATE SKIP LOCKED` makes concurrent claimers take different threads. Only threads
    that are due are claimed (`next_action_at` unset or past); with `batch_id` (tests) the
    thread's `next_action_at` is ignored, which is how held threads are claimed. The claim is
    one statement: call it outside a transaction so the new status is committed at once.
    """
    rows = await conn.fetch(CLAIM_QUEUED, limit, batch_id)
    return [ClaimedThread(**row) for row in rows]


async def count_calls_today(conn: asyncpg.Connection, brand_id: UUID, today: date) -> int:
    """How many calls the brand has placed since UTC midnight of `today`."""
    midnight = datetime.combine(today, time.min, tzinfo=UTC)
    return await conn.fetchval(COUNT_CALLS_SINCE, brand_id, midnight)


async def set_call_conversation(
    conn: asyncpg.Connection, thread_id: UUID, conversation_id: str
) -> None:
    """Remember which ElevenLabs conversation is the thread's call."""
    await conn.execute(SET_CALL_CONVERSATION, thread_id, conversation_id)


async def live_calls(conn: asyncpg.Connection, *, batch_id: UUID | None = None) -> list[LiveCall]:
    """Threads in `calling` or `in_call` that have a conversation id, oldest first.

    A `calling` thread with no conversation id was never placed: the restart sweep fails it.
    """
    rows = await conn.fetch(SELECT_LIVE_CALLS, batch_id)
    return [
        LiveCall(
            thread=ThreadRef(
                id=row["id"],
                batch_id=row["batch_id"],
                brand_id=row["brand_id"],
                creator_id=row["creator_id"],
            ),
            status=row["status"],
            conversation_id=row["call_conversation_id"],
        )
        for row in rows
    ]

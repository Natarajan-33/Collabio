"""The thread event log and conditional status transitions.

Every function takes the caller's connection and leaves the transaction to the caller.
`thread_events` is append-only, and a thread's status only changes through `transition` or
`apply_event`, in the same transaction as the event that explains it. jsonb values go in as
`json.dumps` text cast with `::jsonb`, and come back as text.
"""

import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg

from app.core.thread_state import check_transition
from app.schemas.negotiation import Actor, EventType, NegotiationTerms

TermsSource = Literal["brand", "creator"]

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
    latest_terms_source = coalesce($5, latest_terms_source)
where id = $1 and status = any($6::text[])
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


class StaleThread(Exception):
    """The thread was not in an expected status: someone else moved it first."""


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
    """Record an event and, when `target` is set, move the thread, atomically.

    Returns False without transitioning when the event is a duplicate. `StaleThread`
    propagates and rolls the event back.
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
            return False
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
        return True


async def update_latest_terms(
    conn: asyncpg.Connection, thread_id: UUID, terms: NegotiationTerms, source: TermsSource
) -> None:
    """Set the thread's latest terms without changing its status."""
    await conn.execute(UPDATE_TERMS, thread_id, _terms_json(terms), source)

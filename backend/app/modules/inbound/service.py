"""Creator email replies: from a Resend `email.received` webhook to a thread event.

The webhook carries metadata only, so the body is fetched from Resend. What makes a delivery
safe to repeat (Resend retries, and replays on request):

- The reply is routed by its reply-to token alone (Ruling 12): `t-{token}@{domain}` in `to` or
  `received_for`. An unknown token stops the retries (200) and stores nothing.
- A transcript is unique per `(kind, external_id)` and `email_received` per `(type, external_id)`,
  both written in one transaction under the thread's row lock, so one reply is recorded once
  however many deliveries arrive. The Gemini call happens before that transaction.
- Only a failure to fetch the body is worth a retry (`EmailUnavailable`, which the router turns
  into a 503); nothing has been written by then.

Every reply is recorded as one `email_received` event. A reply that cannot be applied
automatically becomes `needs_review` with a reason the brand can act on. The structurer sees the
ask, the brand's current offer and the stripped reply, never the brand's ceiling or the
creator's floor (spec 3.4).
"""

import logging
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Literal

import asyncpg

from app.adapters.db import Database
from app.adapters.email import EmailPort, EmailRejected, ReceivedEmail
from app.adapters.gemini import GeminiPort
from app.config import Settings
from app.core.email_quotes import html_to_text, parse_reply_address, strip_reply
from app.core.package_text import package_one_liner
from app.core.terms import brand_offer_terms, complete_counter
from app.core.thread_state import CONFIDENCE_FLOOR, status_for_stance
from app.modules.negotiation.calls import load_call_context
from app.modules.negotiation.completion import SELECT_ASK_FORMAT
from app.modules.negotiation.prompts import CallAsk, ReplyContext, StructuredReply
from app.modules.negotiation.structurer import structure_reply
from app.modules.notify import outbox
from app.modules.notify.outbox import OutboxKind
from app.modules.threads import repo
from app.modules.threads.repo import TermsSource, ThreadRef
from app.schemas.negotiation import MAX_PRICE_CENTS, NegotiationTerms

logger = logging.getLogger(__name__)

InboundOutcome = Literal[
    "ignored", "unknown_token", "duplicate", "applied", "needs_review", "recorded"
]

# A reply in one of these moves the thread; `accepted` and `needs_review` only tell the brand;
# every other status (awarded, declined, closed_lost, ...) is recorded without a word.
OPEN_STATUSES = frozenset({"awaiting_reply", "countered", "no_response"})
NOTIFY_STATUSES = frozenset({"accepted", "needs_review"})

NOT_THE_CREATOR = "The reply came from an address that isn't the creator's"
UNREADABLE = "We couldn't read this reply automatically"
UNCLEAR = "The reply wasn't clear enough to apply"
QUESTION = "The creator asked a question"
NO_POSITION = "The creator hasn't taken a position yet"
NO_PRICE = "The reply has no price"
ACCEPTED_AFTER_COUNTER = "The creator accepted after making a counter-offer"
ACCEPTED_WITH_CONDITIONS = "The creator accepted with conditions"
CHANGED = "The negotiation changed while this reply was being read"
AFTER_ACCEPT = "The creator replied after accepting"
AFTER_REVIEW = "The creator sent another reply while this one was waiting for you"

SNIPPET_CHARS = 280

SELECT_THREAD = """
select t.id, t.batch_id, t.brand_id, t.creator_id, t.status, c.email as creator_email
from public.threads t
join public.creators c on c.id = t.creator_id
where t.reply_token = $1
"""
REPLY_RECORDED = """
select exists (
  select 1 from public.thread_events where type = 'email_received' and external_id = $1
)
"""
INSERT_TRANSCRIPT = """
insert into public.transcripts (thread_id, kind, external_id, subject, body_text, summary, raw_text)
values ($1, 'email_in', $2, $3, $4, $5, $6)
on conflict (kind, external_id) do nothing
returning id
"""


class _Duplicate(Exception):
    """The reply was recorded by another delivery first; roll this one back."""


@dataclass(frozen=True)
class _Decision:
    """What one reply does to its thread."""

    target: str | None  # the new status, or None to record without moving the thread
    summary: str
    terms: NegotiationTerms | None = None  # carried by the event
    latest_terms: NegotiationTerms | None = None  # becomes the thread's latest (creator's) terms
    reason: str | None = None
    notify: OutboxKind | None = None


def _snippet(body: str) -> str:
    if not body:
        return "An empty reply."
    return body if len(body) <= SNIPPET_CHARS else body[:SNIPPET_CHARS].rstrip() + "..."


def _review(reason: str, summary: str, terms: NegotiationTerms | None = None) -> _Decision:
    return _Decision(
        "needs_review", summary, terms=terms, reason=reason, notify="brand_needs_review"
    )


def _accepts_with_changes(terms: NegotiationTerms, offer: NegotiationTerms) -> bool:
    """An "accept" that carries conditions or questions, or names a price or video count
    other than the brand's current offer, is not a plain accept."""
    return bool(
        any(c.strip() for c in terms.conditions)
        or any(q.strip() for q in terms.open_questions)
        or (terms.price_cents is not None and terms.price_cents != offer.price_cents)
        or (terms.videos is not None and terms.videos != offer.videos)
    )


def _decide(
    status: str,
    *,
    sender_ok: bool,
    body: str,
    structured: StructuredReply | None,
    offer: NegotiationTerms,
) -> _Decision:
    """The effect of a reply on a thread that is in `status`. Pure."""
    if status not in OPEN_STATUSES:
        if status in NOTIFY_STATUSES:
            reason = AFTER_ACCEPT if status == "accepted" else AFTER_REVIEW
            return _Decision(None, _snippet(body), reason=reason, notify="brand_needs_review")
        return _Decision(None, _snippet(body))
    if not sender_ok:
        return _review(NOT_THE_CREATOR, _snippet(body))
    if structured is None:
        return _review(UNREADABLE, _snippet(body))

    terms, summary = structured.terms, structured.summary
    target = status_for_stance(terms.stance, terms.confidence)
    if target == "needs_review":
        if terms.confidence < CONFIDENCE_FLOOR:
            reason = UNCLEAR
        elif terms.stance == "question":
            reason = QUESTION
        else:
            reason = NO_POSITION
        return _review(reason, summary, terms)
    too_big = terms.price_cents is not None and terms.price_cents > MAX_PRICE_CENTS
    if too_big and target in ("countered", "accepted"):
        return _review(UNCLEAR, summary)  # a misread number must not reach the board
    if target == "countered":
        completed = complete_counter(terms, offer)
        if completed is None:
            return _review(NO_PRICE, summary, terms)
        return _Decision(
            "countered",
            summary,
            terms=completed,
            latest_terms=completed,
            notify="brand_creator_countered",
        )
    if target == "accepted":
        if status == "countered":  # the state machine has no countered -> accepted
            return _review(ACCEPTED_AFTER_COUNTER, summary, terms)
        if _accepts_with_changes(terms, offer):  # booking the brand's offer would be wrong
            return _review(ACCEPTED_WITH_CONDITIONS, summary, terms)
        accepted = offer.model_copy(update={"stance": "accept"})  # Ruling 3
        return _Decision(
            "accepted",
            summary,
            terms=accepted,
            latest_terms=accepted,
            notify="brand_creator_accepted",
        )
    return _Decision("declined", summary, terms=terms, notify="brand_creator_declined")


def _raw_body(received: ReceivedEmail) -> str:
    """The reply as written, quoted history and signature included."""
    if received.text:
        return received.text
    return html_to_text(received.html) if received.html else ""


def _sender_matches(sender: str, creator_email: str) -> bool:
    return parseaddr(sender)[1].strip().lower() == creator_email.strip().lower()


async def _reply_context(conn: asyncpg.Connection, thread: ThreadRef) -> ReplyContext:
    """What the structurer is told: the ask, the creator's package and the brand's offer."""
    call = await load_call_context(conn, thread.id)
    ask_format = await conn.fetchval(SELECT_ASK_FORMAT, thread.id)
    counter = await repo.latest_brand_counter(conn, thread.id)
    return ReplyContext(
        brand_name=call.brand_name,
        ask=CallAsk(
            videos=call.ask_videos,
            price_cents=call.ask_price_cents,
            go_live_by=call.go_live_by,
            format=ask_format,
            package_one_liner=package_one_liner(call.package),
        ),
        brand_offer=brand_offer_terms(
            ask_videos=call.ask_videos,
            ask_price_cents=call.ask_price_cents,
            go_live_by=call.go_live_by,
            format=ask_format,
            counter=counter,
        ),
    )


async def _locked_decision(
    conn: asyncpg.Connection,
    thread: ThreadRef,
    *,
    read_status: str,
    locked_status: str,
    sender_ok: bool,
    body: str,
    structured: StructuredReply | None,
    offer: NegotiationTerms,
) -> _Decision:
    """The decision for the status found under the lock.

    The reply was read (and the brand's offer fetched) in `read_status`. If the thread moved
    meanwhile, the offer is read again, and a reply whose effect depended on the old status
    waits for the brand instead of being applied to a negotiation it never saw.
    """
    decide = {"sender_ok": sender_ok, "body": body, "structured": structured}
    if locked_status == read_status:
        return _decide(locked_status, offer=offer, **decide)
    fresh = (await _reply_context(conn, thread)).brand_offer
    decision = _decide(locked_status, offer=fresh, **decide)
    if locked_status not in OPEN_STATUSES:
        return decision  # closed or waiting on the brand: recorded without moving anything
    if decision == _decide(read_status, offer=offer, **decide):
        return decision
    summary = structured.summary if structured else _snippet(body)
    return _review(CHANGED, summary, structured.terms if structured else None)


async def ingest(
    db: Database,
    *,
    email: EmailPort,
    gemini: GeminiPort | None,
    settings: Settings,
    event: dict,
) -> InboundOutcome:
    """Apply one Resend webhook event. Raises `EmailUnavailable` when the body cannot be
    fetched (nothing is stored then, so a retry starts clean)."""
    data = event.get("data")
    email_id = data.get("email_id") if isinstance(data, dict) else None
    if event.get("type") != "email.received" or not isinstance(email_id, str) or not email_id:
        return "ignored"
    assert isinstance(data, dict)

    addresses = [
        address
        for key in ("to", "received_for")
        for address in (data.get(key) or [])
        if isinstance(address, str)
    ]
    token = parse_reply_address(addresses, settings.resend_inbound_domain)
    if token is None:
        logger.info("Inbound email %s has no reply token", email_id)
        return "unknown_token"

    async with db.acquire() as conn:
        row = await conn.fetchrow(SELECT_THREAD, token)
        if row is None:
            logger.info("Inbound email %s names an unknown reply token", email_id)
            return "unknown_token"
        if await conn.fetchval(REPLY_RECORDED, email_id):
            return "duplicate"
        thread = ThreadRef(
            id=row["id"],
            batch_id=row["batch_id"],
            brand_id=row["brand_id"],
            creator_id=row["creator_id"],
        )
        status, creator_email = row["status"], row["creator_email"]
        context = await _reply_context(conn, thread)

    try:
        received = await email.get_received(email_id)
    except EmailRejected:
        # Resend called the request invalid (400/422): a retry cannot fix it, so the reply is
        # lost. Say so loudly; 401/403/404/409 are `EmailUnavailable` and get retried.
        logger.exception("Resend rejected the fetch of inbound email %s; dropping it", email_id)
        return "ignored"

    raw = _raw_body(received)
    body = strip_reply(raw)
    sender_ok = _sender_matches(received.from_, creator_email)
    structured = None
    if status in OPEN_STATUSES and sender_ok and body:
        structured = await structure_reply(gemini, ctx=context, body=body)

    attachments = len(received.attachments) or len(data.get("attachments") or [])
    subject = received.subject or (
        data.get("subject") if isinstance(data.get("subject"), str) else None
    )
    try:
        async with db.transaction() as conn:
            locked = await conn.fetchval(repo.SELECT_STATUS_FOR_UPDATE, thread.id)
            if locked is None:  # the brief was deleted meanwhile
                return "unknown_token"
            decision = await _locked_decision(
                conn,
                thread,
                read_status=status,
                locked_status=locked,
                sender_ok=sender_ok,
                body=body,
                structured=structured,
                offer=context.brand_offer,
            )
            transcript_id = await conn.fetchval(
                INSERT_TRANSCRIPT, thread.id, email_id, subject, body, decision.summary, raw
            )
            if transcript_id is None:
                raise _Duplicate
            payload: dict = {"summary": decision.summary}
            if decision.reason:
                payload["reason"] = decision.reason
            if attachments:
                payload["attachments_ignored"] = attachments
            source: TermsSource | None = "creator" if decision.latest_terms else None
            event_id = await repo.apply_event_id(
                conn,
                thread,
                expected={locked},
                target=decision.target,
                type="email_received",
                actor="creator",
                payload=payload,
                terms=decision.terms,
                transcript_id=transcript_id,
                external_id=email_id,
                latest_terms=decision.latest_terms,
                latest_terms_source=source,
            )
            if event_id is None:
                raise _Duplicate
            if decision.notify is not None:
                await outbox.enqueue(
                    conn, kind=decision.notify, thread_id=thread.id, event_id=event_id
                )
    except _Duplicate:
        return "duplicate"

    if decision.target is None:
        return "recorded"
    return "needs_review" if decision.target == "needs_review" else "applied"

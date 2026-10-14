"""Deliver outbox rows: claim, compose, render, send through Resend, record the outcome.

A claim increments `attempts` and pushes `next_attempt_at` five minutes ahead in the same
statement (a lease), so a worker that dies mid-send leaves a row that comes due again, and the
retry reuses the Resend idempotency key `outbox:{id}`. Rows are independent: one that cannot be
loaded, rendered or sent is backed off (`30 s x 2^attempts`, `failed` after five attempts) and
never stops the others. Actions queue rows inside their own transactions, so Resend being down
never fails an action.
"""

import json
import logging
from collections.abc import Callable, Collection
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.adapters.email import EmailPort, OutboundEmail
from app.adapters.gemini import GeminiPort
from app.config import Settings
from app.core.contact import first_name, is_reserved_address
from app.core.reply_token import reply_address
from app.modules.notify.compose import NotifyContext, closed_paragraph, compose
from app.modules.notify.render import is_creator_mail, render, unsubscribe_url
from app.schemas.negotiation import NegotiationTerms

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
LEASE = "5 minutes"

CLAIM = f"""
update public.outbox_emails o
set attempts = o.attempts + 1, next_attempt_at = now() + interval '{LEASE}'
where o.id in (
  select id from public.outbox_emails
  where status = 'pending' and next_attempt_at <= now()
    and ($2::uuid[] is null or thread_id = any($2::uuid[]))
  order by next_attempt_at, id
  for update skip locked
  limit $1)
returning o.*
"""
SELECT_CONTEXT = """
select
  t.reply_token, t.batch_id,
  b.brand_name, b.product_name, b.contact_email as brand_email,
  c.name as creator_name, c.email as creator_email,
  e.terms as event_terms, e.payload as event_payload
from public.threads t
join public.batches ba on ba.id = t.batch_id
join public.briefs b on b.id = ba.brief_id
join public.creators c on c.id = t.creator_id
left join public.thread_events e on e.id = $2
where t.id = $1
"""
SELECT_DEAL = "select id, videos, price_cents, go_live_by from public.deals where thread_id = $1"
SELECT_OUTREACH_SUBJECT = """
select payload->>'subject' from public.thread_events
where thread_id = $1 and type = 'email_drafted'
order by id desc limit 1
"""
MARK_SENT = """
update public.outbox_emails
set status = 'sent', resend_id = $2, sent_at = now(), last_error = null
where id = $1
"""
MARK_SKIPPED = """
update public.outbox_emails set status = 'skipped', last_error = $2 where id = $1
"""
MARK_FAILED = f"""
update public.outbox_emails
set last_error = $2,
    next_attempt_at = now() + make_interval(secs => 30 * power(2, attempts)),
    status = case when attempts >= {MAX_ATTEMPTS} then 'failed' else status end
where id = $1 and status = 'pending'
"""
STORE_PAYLOAD = "update public.outbox_emails set payload = payload || $2::jsonb where id = $1"

NO_ADDRESS = "No deliverable address"
NOT_CONFIGURED_FROM = "Email isn't configured (RESEND_FROM)."


def _json(raw: str | None) -> dict:
    return {} if raw is None else json.loads(raw)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


async def load_context(
    conn: asyncpg.Connection, row: asyncpg.Record, settings: Settings
) -> NotifyContext:
    """Everything the row's email is written from. Raises LookupError for a missing thread."""
    thread_id: UUID = row["thread_id"]
    found = await conn.fetchrow(SELECT_CONTEXT, thread_id, row["event_id"])
    if found is None:
        raise LookupError(f"No thread {thread_id}")
    kind = row["kind"]
    payload = _json(row["payload"])
    event_payload = _json(found["event_payload"])
    terms = (
        None
        if found["event_terms"] is None
        else NegotiationTerms.model_validate_json(found["event_terms"])
    )

    deal_id: UUID | None = None
    if kind == "creator_awarded":
        deal = await conn.fetchrow(SELECT_DEAL, thread_id)
        if deal is not None:
            deal_id = deal["id"]
            if terms is None:  # the awarded event carries no terms; the deal has them
                terms = NegotiationTerms(
                    videos=deal["videos"],
                    price_cents=deal["price_cents"],
                    go_live_by=deal["go_live_by"],
                    stance="accept",
                    source="in_app",
                    confidence=1.0,
                )

    creator_mail = kind.startswith("creator_")
    return NotifyContext(
        kind=kind,
        thread_id=thread_id,
        batch_id=found["batch_id"],
        brand_name=found["brand_name"] or "The brand",
        product_name=found["product_name"] or "their product",
        creator_name=found["creator_name"],
        creator_first_name=first_name(found["creator_name"]),
        to_address=found["creator_email"] if creator_mail else found["brand_email"],
        reply_token=found["reply_token"],
        outreach_subject=(
            await conn.fetchval(SELECT_OUTREACH_SUBJECT, thread_id) if creator_mail else None
        ),
        terms=terms,
        note=_text(payload.get("note")) or _text(event_payload.get("note")),
        reason=_text(payload.get("reason")) or _text(event_payload.get("reason")),
        deal_id=deal_id,
        frontend_url=settings.public_frontend_url,
        backend_url=settings.public_backend_url,
        inbound_domain=settings.resend_inbound_domain,
    )


async def _closed_text(
    db: Database, gemini: GeminiPort | None, row: asyncpg.Record, ctx: NotifyContext
) -> tuple[str, bool]:
    """The `creator_closed` paragraph. It is stored on the row once written, so a retry sends
    the same body under the same Resend idempotency key."""
    payload = _json(row["payload"])
    stored = _text(payload.get("closed_paragraph"))
    if stored is not None:
        return stored, bool(payload.get("ai_written"))
    text, ai_written = await closed_paragraph(gemini, ctx)
    async with db.acquire() as conn:
        await conn.execute(
            STORE_PAYLOAD,
            row["id"],
            json.dumps({"closed_paragraph": text, "ai_written": ai_written}),
        )
    return text, ai_written


async def _deliver(
    db: Database,
    row: asyncpg.Record,
    *,
    email: Callable[[], EmailPort],
    gemini: GeminiPort | None,
    settings: Settings,
) -> None:
    outbox_id: int = row["id"]
    async with db.acquire() as conn:
        ctx = await load_context(conn, row, settings)
    if is_reserved_address(ctx.to_address):
        async with db.acquire() as conn:
            await conn.execute(MARK_SKIPPED, outbox_id, NO_ADDRESS)
        return

    paragraph, ai_written = None, False
    if ctx.kind == "creator_closed":
        paragraph, ai_written = await _closed_text(db, gemini, row, ctx)
    content = compose(ctx, closed_paragraph=paragraph).model_copy(update={"ai_written": ai_written})
    rendered = render(content, ctx)

    if not settings.resend_from:
        raise RuntimeError(NOT_CONFIGURED_FROM)
    creator_mail = is_creator_mail(ctx)
    outbound = OutboundEmail(
        to=ctx.to_address or "",
        sender=settings.resend_from,
        reply_to=(
            reply_address(ctx.reply_token, ctx.inbound_domain)
            if creator_mail and ctx.inbound_domain
            else None
        ),
        subject=rendered.subject,
        html=rendered.html,
        text=rendered.text,
        headers=(
            {
                "List-Unsubscribe": f"<{unsubscribe_url(ctx)}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }
            if creator_mail
            else {}
        ),
    )
    resend_id = await email().send(outbound, idempotency_key=f"outbox:{outbox_id}")
    async with db.acquire() as conn:
        await conn.execute(MARK_SENT, outbox_id, resend_id)


async def _record_failure(db: Database, outbox_id: int, exc: Exception) -> None:
    message = (str(exc) or type(exc).__name__)[:500]
    try:
        async with db.acquire() as conn:
            await conn.execute(MARK_FAILED, outbox_id, message)
    except Exception:
        logger.exception("Recording the failure of outbox row %s failed", outbox_id)


async def send_due(
    db: Database,
    *,
    email: Callable[[], EmailPort],
    gemini: GeminiPort | None,
    settings: Settings,
    limit: int = 10,
    thread_ids: Collection[UUID] | None = None,
) -> int:
    """Claim up to `limit` due rows and deliver each; returns how many were processed.

    `email` is a factory called only for a real send. `thread_ids` limits the claim to those
    threads (tests share a database with real rows); production passes None.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(CLAIM, limit, None if thread_ids is None else list(thread_ids))
    for row in rows:
        try:
            await _deliver(db, row, email=email, gemini=gemini, settings=settings)
        except Exception as exc:
            logger.exception(
                "Outbox row %s (%s) failed on attempt %s", row["id"], row["kind"], row["attempts"]
            )
            await _record_failure(db, row["id"], exc)
    return len(rows)

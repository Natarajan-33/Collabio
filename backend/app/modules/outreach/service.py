"""Outreach email: draft with Gemini, render, send through Resend, record what happened.

`send_outreach` takes a thread that is `drafting` through to `awaiting_reply`, or to `failed`
with a reason a person can read. Only the unexpected propagates (the orchestrator isolates it).
A stored draft is reused for the same attempt and the Resend idempotency key is stable per
attempt, so a restart between sending and recording never emails a creator twice.
"""

import json
from collections.abc import Callable
from datetime import date
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.adapters.db import Database
from app.adapters.email import EmailPort, EmailRejected, EmailUnavailable, OutboundEmail
from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.config import Settings
from app.core.contact import is_reserved_address
from app.core.delta import compute_delta
from app.core.reply_token import reply_address
from app.modules.outreach.prompts import (
    OUTREACH_SYSTEM,
    EmailDraft,
    OutreachContext,
    outreach_prompt,
)
from app.modules.outreach.render import RenderedEmail, render_email
from app.modules.threads.repo import (
    StaleThread,
    ThreadRef,
    apply_event,
    fail_thread,
    record_event,
)
from app.schemas.packages import PackageTerms

# Deliberately does not select `budget_ceiling_cents`: the ceiling must never reach a prompt,
# an email, an event payload or a log line.
SELECT_CONTEXT = """
select
  t.id, t.batch_id, t.brand_id, t.creator_id, t.package_id, t.attempts, t.reply_token,
  b.brand_name, b.product_name, b.product_summary, b.negotiation_ask, b.deliverables_format,
  b.deliverables_count, b.ask_price_cents, b.go_live_by, b.flexibility,
  c.name as creator_name, c.bio as creator_bio, c.niches as creator_niches,
  c.email as creator_email,
  p.name as package_name, p.content_type, p.niche, p.volume_count, p.volume_basis,
  p.base_price_cents, p.currency, p.included, p.freebies, p.addons, p.extras,
  p.slots_per_month, p.lead_time_days, p.preferred_channel
from public.threads t
join public.batches ba on ba.id = t.batch_id
join public.briefs b on b.id = ba.brief_id
join public.creators c on c.id = t.creator_id
join public.packages p on p.id = t.package_id
where t.id = $1
"""
SELECT_STATUS = "select status from public.threads where id = $1"
SELECT_DRAFT = """
select payload from public.thread_events
where thread_id = $1 and type = 'email_drafted' and (payload->>'attempt')::int = $2
order by id desc limit 1
"""
INSERT_TRANSCRIPT = """
insert into public.transcripts (thread_id, kind, external_id, subject, body_text)
values ($1, 'email_out', $2, $3, $4)
on conflict (kind, external_id) do update set subject = excluded.subject
returning id
"""

NOT_CONFIGURED_GEMINI = "Email drafting isn't configured (GEMINI_API_KEY)."
GEMINI_FAILED = "Couldn't write the email (model unavailable). Retry to try again."
NOT_CONFIGURED_FROM = "Email isn't configured (RESEND_FROM)."
NOT_CONFIGURED_KEY = "Email isn't configured (RESEND_API_KEY)."
EMAIL_UNAVAILABLE = "Email service unavailable. Retry to try again."


async def load_outreach_context(
    conn: asyncpg.Connection, thread_id: UUID, today: date
) -> OutreachContext:
    """Everything the email is written from. Raises LookupError for an unknown thread."""
    row = await conn.fetchrow(SELECT_CONTEXT, thread_id)
    if row is None:
        raise LookupError(f"No thread {thread_id}")
    package = PackageTerms(
        name=row["package_name"],
        content_type=row["content_type"],
        niche=row["niche"],
        volume_count=row["volume_count"],
        volume_basis=row["volume_basis"],
        base_price_cents=row["base_price_cents"],
        currency=row["currency"],
        included=row["included"],
        freebies=row["freebies"],
        addons=json.loads(row["addons"]),
        extras=json.loads(row["extras"]),
        slots_per_month=row["slots_per_month"],
        lead_time_days=row["lead_time_days"],
        preferred_channel=row["preferred_channel"],
    )
    ask_videos = row["deliverables_count"]
    return OutreachContext(
        thread=ThreadRef(
            id=row["id"],
            batch_id=row["batch_id"],
            brand_id=row["brand_id"],
            creator_id=row["creator_id"],
        ),
        attempts=row["attempts"],
        reply_token=row["reply_token"],
        brand_name=row["brand_name"],
        product_name=row["product_name"],
        product_summary=row["product_summary"],
        negotiation_ask=row["negotiation_ask"],
        deliverables_format=row["deliverables_format"],
        ask_videos=ask_videos,
        ask_price_cents=row["ask_price_cents"],
        go_live_by=row["go_live_by"],
        flexibility=list(row["flexibility"]),
        creator_name=row["creator_name"],
        creator_bio=row["creator_bio"],
        creator_niches=list(row["creator_niches"]),
        creator_email=row["creator_email"],
        package_id=row["package_id"],
        package=package,
        delta=compute_delta(
            row["package_id"],
            package,
            ask_videos=ask_videos,
            ask_price_cents=row["ask_price_cents"],
            go_live_by=row["go_live_by"],
            today=today,
        ),
    )


async def _fail(db: Database, thread_id: UUID, reason: str) -> None:
    async with db.transaction() as conn:
        await fail_thread(conn, thread_id, reason)


async def _stored_draft(conn: asyncpg.Connection, ctx: OutreachContext) -> EmailDraft | None:
    payload = await conn.fetchval(SELECT_DRAFT, ctx.thread.id, ctx.attempts)
    if payload is None:
        return None
    stored = json.loads(payload)
    return EmailDraft(subject=stored["subject"], **stored["draft"])


async def _draft_and_render(
    db: Database,
    gemini: GeminiPort | None,
    settings: Settings,
    ctx: OutreachContext,
) -> tuple[EmailDraft, RenderedEmail] | None:
    """The draft for this attempt (reused if stored, else written and stored) with its
    rendering, or None after failing the thread."""
    thread_id = ctx.thread.id
    offer_url = f"{settings.public_frontend_url}/creator/offers/{thread_id}"
    unsubscribe_url = f"{settings.public_backend_url}/api/v1/unsubscribe/{ctx.reply_token}"

    async with db.acquire() as conn:
        draft = await _stored_draft(conn, ctx)
    if draft is not None:
        rendered = render_email(ctx, draft, offer_url=offer_url, unsubscribe_url=unsubscribe_url)
        return draft, rendered

    if gemini is None:
        await _fail(db, thread_id, NOT_CONFIGURED_GEMINI)
        return None
    try:
        draft = await gemini.generate_structured(
            system=OUTREACH_SYSTEM, prompt=outreach_prompt(ctx), schema=EmailDraft
        )
    except (GeminiUnavailable, GeminiInvalidOutput):
        await _fail(db, thread_id, GEMINI_FAILED)
        return None
    rendered = render_email(ctx, draft, offer_url=offer_url, unsubscribe_url=unsubscribe_url)
    async with db.transaction() as conn:
        await record_event(
            conn,
            ctx.thread,
            type="email_drafted",
            actor="system",
            payload={
                "attempt": ctx.attempts,
                "subject": rendered.subject,
                "body_text": rendered.text,
                "draft": draft.model_dump(exclude={"subject"}),
            },
        )
    return draft, rendered


async def send_outreach(
    db: Database,
    *,
    gemini: GeminiPort | None,
    email: Callable[[], EmailPort],
    settings: Settings,
    thread_id: UUID,
    today: date,
) -> None:
    """Write and send the outreach email for a `drafting` thread.

    `email` is a factory called only for a real send, so threads for reserved addresses work
    without Resend configured.
    """
    async with db.acquire() as conn:
        if await conn.fetchval(SELECT_STATUS, thread_id) != "drafting":
            return  # someone else has it
        ctx = await load_outreach_context(conn, thread_id, today)

    drafted = await _draft_and_render(db, gemini, settings, ctx)
    if drafted is None:
        return
    _, rendered = drafted

    if is_reserved_address(ctx.creator_email):
        await _record_sent(db, ctx, delivered=False)
        return

    if not settings.resend_from:
        await _fail(db, thread_id, NOT_CONFIGURED_FROM)
        return
    try:
        port = email()
    except (ValueError, HTTPException):
        await _fail(db, thread_id, NOT_CONFIGURED_KEY)
        return

    unsubscribe_url = f"{settings.public_backend_url}/api/v1/unsubscribe/{ctx.reply_token}"
    outbound = OutboundEmail(
        to=ctx.creator_email or "",
        sender=settings.resend_from,
        reply_to=(
            reply_address(ctx.reply_token, settings.resend_inbound_domain)
            if settings.resend_inbound_domain
            else None
        ),
        subject=rendered.subject,
        html=rendered.html,
        text=rendered.text,
        headers={
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )
    try:
        email_id = await port.send(
            outbound, idempotency_key=f"thread:{thread_id}:email:{ctx.attempts}"
        )
    except EmailRejected as exc:
        await _fail(db, thread_id, f"Email rejected: {exc}")
        return
    except EmailUnavailable:
        await _fail(db, thread_id, EMAIL_UNAVAILABLE)
        return

    await _record_sent(db, ctx, delivered=True, email_id=email_id, rendered=rendered)


async def _record_sent(
    db: Database,
    ctx: OutreachContext,
    *,
    delivered: bool,
    email_id: str | None = None,
    rendered: RenderedEmail | None = None,
) -> None:
    """In one transaction: the transcript (when sent), the `email_sent` event, and the move
    from `drafting` to `awaiting_reply`."""
    try:
        async with db.transaction() as conn:
            transcript_id = None
            if rendered is not None:
                transcript_id = await conn.fetchval(
                    INSERT_TRANSCRIPT, ctx.thread.id, email_id, rendered.subject, rendered.text
                )
            await apply_event(
                conn,
                ctx.thread,
                expected={"drafting"},
                target="awaiting_reply",
                type="email_sent",
                actor="system",
                payload={"delivered": delivered},
                transcript_id=transcript_id,
                external_id=email_id,
            )
    except StaleThread:
        return  # the thread was moved while the email went out; nothing left to record

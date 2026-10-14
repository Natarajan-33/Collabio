"""Sample negotiation outreach email: draft with Gemini, send with Resend; inbox not stored."""

import logging
from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID

from app.adapters.db import Database
from app.adapters.email import EmailPort, EmailRejected, EmailUnavailable, OutboundEmail
from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.config import Settings
from app.core.contact import first_name, is_reserved_address
from app.core.reply_token import new_reply_token
from app.modules.outreach.prompts import OUTREACH_SYSTEM, EmailDraft, outreach_prompt
from app.modules.outreach.render import render_email
from app.modules.outreach.service import load_outreach_context
from app.modules.threads import repo as threads_repo
from app.modules.voice.try_call import (
    INSERT_TRY_BATCH,
    INSERT_TRY_BRIEF,
    SCENARIOS,
    TryCallRateLimited,
    _load_demo,
)
from app.schemas.voice_try import TryCallScenario

logger = logging.getLogger(__name__)

MAX_TRY_EMAILS_PER_USER_PER_DAY = 10

COUNT_TRY_EMAILS = """
select count(*)::int from public.thread_events
where type = 'email_sent'
  and payload->>'voice_try' = 'true'
  and payload->>'initiator_id' = $1
  and created_at >= now() - interval '24 hours'
"""

INSERT_TRY_THREAD_EMAIL = """
insert into public.threads
  (batch_id, brand_id, creator_id, package_id, channel_plan, status, reply_token)
values ($1, $2, $3, $4, 'email', 'drafting', $5)
returning id
"""

NOT_CONFIGURED_FROM = "Email isn't configured (RESEND_FROM)."
GEMINI_FAILED = "Couldn't write the sample email. Try again in a moment."
EMAIL_UNAVAILABLE = "Email service unavailable. Try again in a moment."


class TryEmailNotConfigured(Exception):
    """Resend or Gemini is missing for the demo email."""


async def _assert_email_rate_limit(conn, initiator_id: UUID) -> None:
    count = await conn.fetchval(COUNT_TRY_EMAILS, str(initiator_id))
    if count >= MAX_TRY_EMAILS_PER_USER_PER_DAY:
        raise TryCallRateLimited


async def _create_try_email_thread(
    conn,
    *,
    brand,
    creator,
    scenario,
    today: date,
    scenario_id: TryCallScenario,
    initiator_id: UUID,
) -> UUID:
    go_live = today + timedelta(days=scenario.go_live_days)
    brief_id = await conn.fetchval(
        INSERT_TRY_BRIEF,
        brand["brand_id"],
        brand["product_id"],
        brand["company_name"],
        brand["product_name"],
        brand["product_summary"],
        scenario.deliverables_count,
        go_live,
        scenario.budget_ceiling_cents,
        scenario.ask_price_cents,
        scenario.negotiation_ask,
        scenario.flexibility,
        [creator["creator_id"]],
        brand["contact_email"],
    )
    batch_id = await conn.fetchval(INSERT_TRY_BATCH, brief_id, brand["brand_id"])
    return await conn.fetchval(
        INSERT_TRY_THREAD_EMAIL,
        batch_id,
        brand["brand_id"],
        creator["creator_id"],
        creator["package_id"],
        new_reply_token(),
    )


async def send_try_email(
    db: Database,
    *,
    gemini: GeminiPort | None,
    email: EmailPort,
    settings: Settings,
    initiator_id: UUID,
    display_name: str | None,
    to_email: str,
    scenario_id: TryCallScenario,
    today: date,
) -> str:
    """Draft and send a sample outreach email to `to_email`. The address is not saved on the profile."""
    if is_reserved_address(to_email):
        raise ValueError("reserved_email")

    if not settings.resend_from:
        raise TryEmailNotConfigured(NOT_CONFIGURED_FROM)

    spec = SCENARIOS[scenario_id]

    async with db.transaction() as conn:
        await _assert_email_rate_limit(conn, initiator_id)
        brand, creator = await _load_demo(conn)
        thread_id = await _create_try_email_thread(
            conn,
            brand=brand,
            creator=creator,
            scenario=spec,
            today=today,
            scenario_id=scenario_id,
            initiator_id=initiator_id,
        )

    async with db.acquire() as conn:
        ctx = await load_outreach_context(conn, thread_id, today)

    first = first_name(display_name or "")
    ctx = replace(
        ctx,
        creator_name=first or ctx.creator_name,
        creator_email=to_email,
    )

    if gemini is None:
        await _fail_demo(db, thread_id, GEMINI_FAILED)
        raise TryEmailNotConfigured(GEMINI_FAILED)

    try:
        draft = await gemini.generate_structured(
            system=OUTREACH_SYSTEM,
            prompt=outreach_prompt(ctx),
            schema=EmailDraft,
        )
    except (GeminiUnavailable, GeminiInvalidOutput):
        await _fail_demo(db, thread_id, GEMINI_FAILED)
        raise TryEmailNotConfigured(GEMINI_FAILED)

    offer_url = f"{settings.public_frontend_url.rstrip('/')}/creator/packages"
    unsubscribe_url = f"{settings.public_backend_url.rstrip('/')}/api/v1/unsubscribe/{ctx.reply_token}"
    rendered = render_email(ctx, draft, offer_url=offer_url, unsubscribe_url=unsubscribe_url)

    outbound = OutboundEmail(
        to=to_email,
        sender=settings.resend_from,
        reply_to=None,
        subject=f"[Collabio sample] {rendered.subject}",
        html=rendered.html,
        text=rendered.text,
        headers={},
    )
    idempotency_key = f"try-email:{initiator_id}:{thread_id}"
    try:
        email_id = await email.send(outbound, idempotency_key=idempotency_key)
    except EmailRejected as exc:
        await _fail_demo(db, thread_id, f"Email rejected: {exc}")
        raise
    except EmailUnavailable:
        await _fail_demo(db, thread_id, EMAIL_UNAVAILABLE)
        raise TryEmailNotConfigured(EMAIL_UNAVAILABLE)

    async with db.transaction() as conn:
        await threads_repo.apply_event(
            conn,
            ctx.thread,
            expected={"drafting"},
            target="awaiting_reply",
            type="email_sent",
            actor="brand_agent",
            payload={
                "voice_try": True,
                "initiator_id": str(initiator_id),
                "delivered": True,
                "subject": rendered.subject,
            },
            external_id=email_id,
        )
    logger.info("Sent try email to %s (thread %s, resend %s)", to_email, thread_id, email_id)
    return rendered.subject


async def _fail_demo(db: Database, thread_id: UUID, reason: str) -> None:
    async with db.transaction() as conn:
        await threads_repo.fail_thread(conn, thread_id, reason)

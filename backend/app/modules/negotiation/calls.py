"""Outbound agent calls: what the negotiation agent is told, and placing the call.

`CallContext` deliberately has no field for the brand's budget ceiling, and its query does not
select it: whatever is not in the context cannot reach the agent's dynamic variables (spec 6.2).
The creator's phone number is used only to dial: it never goes into an event payload or a log.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.adapters.elevenlabs import CallPlacementFailed, ElevenLabsPort, ElevenLabsUnavailable
from app.config import Settings
from app.core.contact import first_name
from app.core.guardrails import MAX_CALLS_PER_BRAND_PER_DAY, call_allowed
from app.core.money import format_cents
from app.core.package_text import package_one_liner
from app.modules.threads import repo
from app.modules.threads.repo import ThreadRef
from app.schemas.packages import PackageTerms

# Deliberately does not select `budget_ceiling_cents`.
SELECT_CONTEXT = """
select
  t.id, t.batch_id, t.brand_id, t.creator_id, t.status,
  b.brand_name, b.product_summary, b.deliverables_count, b.ask_price_cents, b.go_live_by,
  b.flexibility,
  c.name as creator_name, c.phone, c.phone_opt_in,
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

DAILY_LIMIT = f"Daily call limit reached ({MAX_CALLS_PER_BRAND_PER_DAY} calls)."
NOT_CONFIGURED = (
    "Calls aren't configured (ELEVENLABS_NEGOTIATION_AGENT_ID, ELEVENLABS_PHONE_NUMBER_ID)."
)
NO_OPT_IN = "No phone opt-in."
VOICE_UNAVAILABLE = "Voice service unavailable. Retry to call again."

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallContext:
    thread: ThreadRef
    brand_name: str
    product_summary: str
    creator_name: str
    phone: str | None
    phone_opt_in: bool
    package_name: str
    package: PackageTerms
    ask_videos: int
    ask_price_cents: int
    go_live_by: date
    flexibility: list[str]


async def load_call_context(conn: asyncpg.Connection, thread_id: UUID) -> CallContext:
    """Everything the agent is told about the call. Raises LookupError for an unknown thread."""
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
    return CallContext(
        thread=ThreadRef(
            id=row["id"],
            batch_id=row["batch_id"],
            brand_id=row["brand_id"],
            creator_id=row["creator_id"],
        ),
        brand_name=row["brand_name"],
        product_summary=row["product_summary"],
        creator_name=row["creator_name"],
        phone=row["phone"],
        phone_opt_in=row["phone_opt_in"],
        package_name=row["package_name"],
        package=package,
        ask_videos=row["deliverables_count"],
        ask_price_cents=row["ask_price_cents"],
        go_live_by=row["go_live_by"],
        flexibility=list(row["flexibility"]),
    )


def dynamic_variables(ctx: CallContext) -> dict[str, str]:
    """The negotiation agent's dynamic variables: exactly these keys, never the ceiling."""
    return {
        "thread_id": str(ctx.thread.id),
        "creator_first_name": first_name(ctx.creator_name),
        "brand_name": ctx.brand_name,
        "product_summary": ctx.product_summary,
        "package_name": ctx.package_name,
        "package_terms": package_one_liner(ctx.package),
        "ask_videos": str(ctx.ask_videos),
        "ask_price": format_cents(ctx.ask_price_cents),
        "go_live_by": f"{ctx.go_live_by:%B} {ctx.go_live_by.day}, {ctx.go_live_by.year}",
        "flexibility": ", ".join(ctx.flexibility) if ctx.flexibility else "none",
        "follow_up_context": "",
    }


def _scrub_phone(message: str, phone: str) -> str:
    """`message` with the number (with or without `+`, digits only, or split by spaces, dots,
    dashes and brackets) replaced: ElevenLabs' refusals can name the dialed number, and the
    reason is brand-facing."""
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return message
    pattern = r"\+?" + r"[\s().-]*".join(digits)
    return re.sub(pattern, "the creator's number", message)


async def _fail(db: Database, thread_id: UUID, reason: str) -> None:
    async with db.transaction() as conn:
        await repo.fail_thread(conn, thread_id, reason)


async def start_call(
    db: Database,
    *,
    elevenlabs: ElevenLabsPort | None,
    settings: Settings,
    thread_id: UUID,
    today: date,
) -> None:
    """Place the agent's call for a `calling` thread, or fail the thread with a reason.

    Not retried automatically: a failure is final until a person clicks Retry. Once the call
    is placed, the conversation id is stored with the `call_placed` event; the call watcher
    takes it from there.
    """
    async with db.acquire() as conn:
        status = await conn.fetchval(repo.SELECT_STATUS, thread_id)
        if status != "calling":
            return  # someone else has it
        ctx = await load_call_context(conn, thread_id)
        placed_today = await repo.count_calls_today(conn, ctx.thread.brand_id, today)

    if placed_today >= MAX_CALLS_PER_BRAND_PER_DAY:
        await _fail(db, thread_id, DAILY_LIMIT)
        return
    agent_id = settings.elevenlabs_negotiation_agent_id
    phone_number_id = settings.elevenlabs_phone_number_id
    if elevenlabs is None or not agent_id or not phone_number_id:
        await _fail(db, thread_id, NOT_CONFIGURED)
        return
    if not call_allowed(ctx.phone, ctx.phone_opt_in) or ctx.phone is None:
        await _fail(db, thread_id, NO_OPT_IN)
        return

    try:
        conversation_id = await elevenlabs.place_call(
            agent_id=agent_id,
            phone_number_id=phone_number_id,
            to_number=ctx.phone,
            dynamic_variables=dynamic_variables(ctx),
        )
    except CallPlacementFailed as exc:
        await _fail(db, thread_id, f"Call couldn't be placed: {_scrub_phone(str(exc), ctx.phone)}")
        return
    except ElevenLabsUnavailable:
        await _fail(db, thread_id, VOICE_UNAVAILABLE)
        return

    async with db.transaction() as conn:
        await repo.set_call_conversation(conn, thread_id, conversation_id)
        await repo.record_event(
            conn,
            ctx.thread,
            type="call_placed",
            actor="brand_agent",
            payload={},
            external_id=conversation_id,
        )
    logger.info("Placed call for thread %s (conversation %s)", thread_id, conversation_id)

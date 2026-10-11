"""One-off negotiation demo calls: dial the user's phone without saving it."""

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.adapters.elevenlabs import CallPlacementFailed, ElevenLabsPort, ElevenLabsUnavailable
from app.config import Settings
from app.core.contact import first_name
from app.core.reply_token import new_reply_token
from app.modules.negotiation.calls import (
    NOT_CONFIGURED,
    VOICE_UNAVAILABLE,
    _scrub_phone,
    dynamic_variables,
    load_call_context,
)
from app.modules.threads import repo as threads_repo
from app.schemas.voice_try import TryCallScenario

logger = logging.getLogger(__name__)

MAX_TRY_CALLS_PER_USER_PER_DAY = 10
DEMO_BRAND_NAME = "Lumen Audio"
DEMO_CREATOR_HANDLE = "arjuntech"

SELECT_DEMO_BRAND = """
select b.id as brand_id, b.contact_email, p.id as product_id,
       b.company_name, p.name as product_name, p.summary as product_summary
from public.brands b
join public.products p on p.brand_id = b.id
where b.company_name = $1
order by p.id
limit 1
"""
SELECT_CREATOR_PACKAGE = """
select c.id as creator_id, p.id as package_id
from public.creators c
join public.packages p on p.creator_id = c.id and p.status = 'published'
where c.handle = $1
order by p.base_price_cents, p.id
limit 1
"""
# Only successful demo dials count; failed 503/DB attempts do not burn the quota.
COUNT_TRY_CALLS = """
select count(*)::int from public.thread_events
where type = 'call_placed'
  and payload->>'voice_try' = 'true'
  and payload->>'initiator_id' = $1
  and created_at >= now() - interval '24 hours'
"""
INSERT_TRY_BRIEF = """
insert into public.briefs (
  brand_id, product_id, status, brand_name, product_name, product_summary,
  deliverables_count, deliverables_format, deliverable_length_s, go_live_by,
  budget_ceiling_cents, ask_price_cents, negotiation_ask, flexibility, creator_ids,
  contact_email, approved_at
)
values ($1, $2, 'launched', $3, $4, $5, $6, 'short_video', 60, $7, $8, $9, $10, $11, $12, $13, now())
returning id
"""
INSERT_TRY_BATCH = """
insert into public.batches (brief_id, brand_id, follow_up_policy)
values ($1, $2, 'off')
returning id
"""
INSERT_TRY_THREAD = """
insert into public.threads
  (batch_id, brand_id, creator_id, package_id, channel_plan, status, reply_token)
values ($1, $2, $3, $4, 'call', 'calling', $5)
returning id
"""


class DemoNotConfigured(Exception):
    """The seeded demo brand or creator package is missing."""


class TryCallRateLimited(Exception):
    """This user already placed the maximum demo calls today."""


class InvalidPhone(Exception):
    """The phone number failed a final sanity check before dial."""


@dataclass(frozen=True)
class ScenarioSpec:
    deliverables_count: int
    ask_price_cents: int
    budget_ceiling_cents: int
    flexibility: list[str]
    negotiation_ask: str
    go_live_days: int


SCENARIOS: dict[TryCallScenario, ScenarioSpec] = {
    "standard": ScenarioSpec(
        deliverables_count=3,
        ask_price_cents=100_000,
        budget_ceiling_cents=120_000,
        flexibility=["timeline", "price"],
        negotiation_ask="Three short videos for the Lumen Pods launch",
        go_live_days=30,
    ),
    "single_video": ScenarioSpec(
        deliverables_count=1,
        ask_price_cents=80_000,
        budget_ceiling_cents=95_000,
        flexibility=["price"],
        negotiation_ask="One short review video for Lumen Pods",
        go_live_days=21,
    ),
    "rush": ScenarioSpec(
        deliverables_count=2,
        ask_price_cents=110_000,
        budget_ceiling_cents=125_000,
        flexibility=["timeline"],
        negotiation_ask="Two videos with a tight go-live for Lumen Pods",
        go_live_days=14,
    ),
}

_E164 = re.compile(r"^\+[1-9][0-9]{1,14}$")


async def _assert_rate_limit(conn: asyncpg.Connection, initiator_id: UUID) -> None:
    count = await conn.fetchval(COUNT_TRY_CALLS, str(initiator_id))
    if count >= MAX_TRY_CALLS_PER_USER_PER_DAY:
        raise TryCallRateLimited


async def _load_demo(conn: asyncpg.Connection) -> tuple[asyncpg.Record, asyncpg.Record]:
    brand = await conn.fetchrow(SELECT_DEMO_BRAND, DEMO_BRAND_NAME)
    creator = await conn.fetchrow(SELECT_CREATOR_PACKAGE, DEMO_CREATOR_HANDLE)
    if brand is None or creator is None:
        raise DemoNotConfigured
    return brand, creator


async def _create_try_thread(
    conn: asyncpg.Connection,
    *,
    brand: asyncpg.Record,
    creator: asyncpg.Record,
    scenario: ScenarioSpec,
    today: date,
    initiator_id: UUID,
    scenario_id: TryCallScenario,
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
    thread_id = await conn.fetchval(
        INSERT_TRY_THREAD,
        batch_id,
        brand["brand_id"],
        creator["creator_id"],
        creator["package_id"],
        new_reply_token(),
    )
    ref = threads_repo.ThreadRef(
        id=thread_id,
        batch_id=batch_id,
        brand_id=brand["brand_id"],
        creator_id=creator["creator_id"],
    )
    await threads_repo.record_event(
        conn,
        ref,
        type="queued",
        actor="system",
        payload={
            "voice_try": True,
            "initiator_id": str(initiator_id),
            "scenario": scenario_id,
        },
    )
    return thread_id


async def place_try_call(
    db: Database,
    *,
    elevenlabs: ElevenLabsPort | None,
    settings: Settings,
    initiator_id: UUID,
    display_name: str | None,
    phone: str,
    scenario_id: TryCallScenario,
    today: date,
) -> None:
    """Dial `phone` for a sandbox negotiation. The number is never written to the database."""
    if not _E164.match(phone):
        raise InvalidPhone

    spec = SCENARIOS[scenario_id]
    agent_id = settings.elevenlabs_negotiation_agent_id
    phone_number_id = settings.elevenlabs_phone_number_id
    if elevenlabs is None or not agent_id or not phone_number_id:
        raise DemoNotConfigured(NOT_CONFIGURED)

    async with db.transaction() as conn:
        await _assert_rate_limit(conn, initiator_id)
        brand, creator = await _load_demo(conn)
        thread_id = await _create_try_thread(
            conn,
            brand=brand,
            creator=creator,
            scenario=spec,
            today=today,
            initiator_id=initiator_id,
            scenario_id=scenario_id,
        )

    async with db.acquire() as conn:
        ctx = await load_call_context(conn, thread_id)
    variables = dynamic_variables(ctx)
    first = first_name(display_name or "")
    variables["creator_first_name"] = first or "there"
    variables["follow_up_context"] = "This is a product demo call."

    try:
        conversation_id = await elevenlabs.place_call(
            agent_id=agent_id,
            phone_number_id=phone_number_id,
            to_number=phone,
            dynamic_variables=variables,
        )
    except CallPlacementFailed as exc:
        await _fail_try(db, thread_id, f"Call couldn't be placed: {_scrub_phone(str(exc), phone)}")
        raise exc
    except ElevenLabsUnavailable:
        await _fail_try(db, thread_id, VOICE_UNAVAILABLE)
        raise

    async with db.transaction() as conn:
        await threads_repo.set_call_conversation(conn, thread_id, conversation_id)
        await threads_repo.record_event(
            conn,
            ctx.thread,
            type="call_placed",
            actor="brand_agent",
            payload={"voice_try": True, "initiator_id": str(initiator_id)},
            external_id=conversation_id,
        )
    logger.info(
        "Placed try call for profile %s (thread %s, conversation %s)",
        initiator_id,
        thread_id,
        conversation_id,
    )


async def _fail_try(db: Database, thread_id: UUID, reason: str) -> None:
    async with db.transaction() as conn:
        await threads_repo.fail_thread(conn, thread_id, reason)

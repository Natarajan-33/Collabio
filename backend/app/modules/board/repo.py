"""Board queries. Every statement is scoped to one brand: the backend's connection bypasses
row-level security, so ownership is enforced here by `brand_id`.

Creators are selected by public columns only (never `email` or `phone`), packages without
their floor. The brief's ceiling is read for the ranking and the brand-only brief summary.
jsonb values come back as text.
"""

import json
from typing import Any
from uuid import UUID

import asyncpg

SELECT_BATCH_LIST = """
select ba.id, ba.brief_id, br.product_name, ba.launched_at,
  count(t.id) as thread_count,
  count(t.id) filter (where exists (
    select 1 from public.thread_events e
    where e.thread_id = t.id and e.type in ('email_sent', 'call_started'))) as contacted,
  count(t.id) filter (where exists (
    select 1 from public.thread_events e
    where e.thread_id = t.id and e.type = any($2::text[]))) as replied,
  count(t.id) filter (where t.status = 'countered') as countered
from public.batches ba
join public.briefs br on br.id = ba.brief_id
left join public.threads t on t.batch_id = ba.id
where ba.brand_id = $1
group by ba.id, br.product_name
order by ba.launched_at desc, ba.id
"""
SELECT_BATCH = """
select ba.id, ba.brief_id, ba.launched_at, ba.follow_up_policy, ba.hires_target,
  br.product_name, br.deliverables_count, br.deliverables_format, br.ask_price_cents,
  br.budget_ceiling_cents, br.go_live_by
from public.batches ba
join public.briefs br on br.id = ba.brief_id
where ba.brand_id = $1 and ba.id = $2
"""
SELECT_THREAD_BATCH = "select batch_id from public.threads where brand_id = $1 and id = $2"
# `similarity` is null when the creator or the batch has no embedding.
SELECT_THREADS = """
select t.id, t.channel_plan, t.status, t.latest_terms, t.latest_terms_source, t.last_error,
  t.expires_at, t.created_at, t.updated_at, t.package_id, d.id as deal_id,
  c.id as creator_id, c.name as creator_name, c.handle as creator_handle,
  c.engagement_rate,
  case when c.embedding is null or ba.brief_embedding is null then null
       else 1 - (c.embedding <=> ba.brief_embedding) end as similarity,
  json_build_object(
    'name', p.name,
    'content_type', p.content_type,
    'niche', p.niche,
    'volume_count', p.volume_count,
    'volume_basis', p.volume_basis,
    'base_price_cents', p.base_price_cents,
    'currency', p.currency,
    'included', p.included,
    'freebies', p.freebies,
    'addons', p.addons,
    'extras', p.extras,
    'slots_per_month', p.slots_per_month,
    'lead_time_days', p.lead_time_days,
    'preferred_channel', p.preferred_channel
  ) as package
from public.threads t
join public.batches ba on ba.id = t.batch_id
join public.creators c on c.id = t.creator_id
join public.packages p on p.id = t.package_id
left join public.deals d on d.thread_id = t.id
where t.brand_id = $1 and t.batch_id = $2
order by t.created_at, t.id
"""
SELECT_BATCH_EVENTS = """
select id, thread_id, type, actor, created_at, payload, terms
from public.thread_events
where brand_id = $1 and batch_id = $2
order by id
"""
SELECT_THREAD_EVENTS = """
select id, thread_id, type, actor, created_at, payload, terms
from public.thread_events
where brand_id = $1 and thread_id = $2
order by id
"""
SELECT_THREAD_TRANSCRIPTS = """
select tr.id, tr.kind, tr.created_at, tr.subject, tr.body_text, tr.turns, tr.summary
from public.transcripts tr
join public.threads t on t.id = tr.thread_id
where t.brand_id = $1 and tr.thread_id = $2
order by tr.created_at desc, tr.id
"""
RESET_FOR_RETRY = """
update public.threads
set attempts = attempts + 1, last_error = null, call_conversation_id = null,
    next_action_at = null
where id = $1
"""


# Statuses that count as the creator having answered (the board's "replied" KPI).
REPLY_EVENTS = ("call_ended", "email_received", "counter_submitted", "accepted", "declined")

SELECT_STATUS_FOR_UPDATE = "select status from public.threads where id = $1 for update"
# The brand's own thread with its brief and package. The brief's ceiling is read here for the
# brand's counter check; it goes no further than the service.
SELECT_THREAD_CONTEXT = """
select t.id, t.status, t.package_id, ba.id as batch_id,
  br.product_name, br.deliverables_count, br.deliverables_format, br.ask_price_cents,
  br.budget_ceiling_cents, br.go_live_by,
  json_build_object(
    'name', p.name,
    'content_type', p.content_type,
    'niche', p.niche,
    'volume_count', p.volume_count,
    'volume_basis', p.volume_basis,
    'base_price_cents', p.base_price_cents,
    'currency', p.currency,
    'included', p.included,
    'freebies', p.freebies,
    'addons', p.addons,
    'extras', p.extras,
    'slots_per_month', p.slots_per_month,
    'lead_time_days', p.lead_time_days,
    'preferred_channel', p.preferred_channel
  ) as package
from public.threads t
join public.batches ba on ba.id = t.batch_id
join public.briefs br on br.id = ba.brief_id
join public.packages p on p.id = t.package_id
where t.brand_id = $1 and t.id = $2
"""
SELECT_BATCH_THREAD_STATUSES = """
select t.id, t.status, c.id as creator_id, c.name as creator_name, c.handle as creator_handle
from public.threads t
join public.creators c on c.id = t.creator_id
where t.brand_id = $1 and t.batch_id = $2
order by t.created_at, t.id
"""


def _loads(value: str | None) -> Any:
    return None if value is None else json.loads(value)


async def list_batches(conn: asyncpg.Connection, brand_id: UUID) -> list[dict[str, Any]]:
    return [dict(row) for row in await conn.fetch(SELECT_BATCH_LIST, brand_id, list(REPLY_EVENTS))]


async def get_batch(
    conn: asyncpg.Connection, brand_id: UUID, batch_id: UUID
) -> dict[str, Any] | None:
    row = await conn.fetchrow(SELECT_BATCH, brand_id, batch_id)
    return None if row is None else dict(row)


async def batch_of_thread(conn: asyncpg.Connection, brand_id: UUID, thread_id: UUID) -> UUID | None:
    return await conn.fetchval(SELECT_THREAD_BATCH, brand_id, thread_id)


async def batch_threads(
    conn: asyncpg.Connection, brand_id: UUID, batch_id: UUID
) -> list[dict[str, Any]]:
    rows = await conn.fetch(SELECT_THREADS, brand_id, batch_id)
    return [
        dict(row)
        | {
            "latest_terms": _loads(row["latest_terms"]),
            "package": _loads(row["package"]),
            "engagement_rate": None
            if row["engagement_rate"] is None
            else float(row["engagement_rate"]),
        }
        for row in rows
    ]


def _event(row: asyncpg.Record) -> dict[str, Any]:
    return dict(row) | {"payload": _loads(row["payload"]), "terms": _loads(row["terms"])}


async def batch_events(
    conn: asyncpg.Connection, brand_id: UUID, batch_id: UUID
) -> list[dict[str, Any]]:
    """Every event of the batch, oldest first."""
    return [_event(row) for row in await conn.fetch(SELECT_BATCH_EVENTS, brand_id, batch_id)]


async def thread_events(
    conn: asyncpg.Connection, brand_id: UUID, thread_id: UUID
) -> list[dict[str, Any]]:
    return [_event(row) for row in await conn.fetch(SELECT_THREAD_EVENTS, brand_id, thread_id)]


async def thread_transcripts(
    conn: asyncpg.Connection, brand_id: UUID, thread_id: UUID
) -> list[dict[str, Any]]:
    """The thread's transcripts, newest first."""
    rows = await conn.fetch(SELECT_THREAD_TRANSCRIPTS, brand_id, thread_id)
    return [dict(row) | {"turns": _loads(row["turns"])} for row in rows]


async def reset_for_retry(conn: asyncpg.Connection, thread_id: UUID) -> None:
    await conn.execute(RESET_FOR_RETRY, thread_id)


async def lock_status(conn: asyncpg.Connection, thread_id: UUID) -> str:
    """Lock the thread row until the caller's transaction ends and return its status."""
    return await conn.fetchval(SELECT_STATUS_FOR_UPDATE, thread_id)


async def thread_context(
    conn: asyncpg.Connection, brand_id: UUID, thread_id: UUID
) -> dict[str, Any] | None:
    """The brand's thread with its brief (ceiling included) and package, or None."""
    row = await conn.fetchrow(SELECT_THREAD_CONTEXT, brand_id, thread_id)
    return None if row is None else dict(row) | {"package": _loads(row["package"])}


async def batch_thread_statuses(
    conn: asyncpg.Connection, brand_id: UUID, batch_id: UUID
) -> list[dict[str, Any]]:
    """Every thread of the batch with its status and creator chip fields, oldest first."""
    return [dict(r) for r in await conn.fetch(SELECT_BATCH_THREAD_STATUSES, brand_id, batch_id)]

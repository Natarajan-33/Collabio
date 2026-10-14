"""Deal queries. Every statement is scoped to the calling brand or creator: the backend's
connection bypasses row-level security, so ownership is enforced here.

This module reads the brief's budget ceiling (for the award check) and, in `get_deal`, the two
contact emails that a booked deal reveals (`creators.email`, `briefs.contact_email`). Nothing
else in the app sends them to the other side. Phone numbers are never selected. jsonb values
come back as text.
"""

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import asyncpg

from app.schemas.deals import AgreedTerms, MilestoneDraft

SELECT_AWARD_CONTEXT = """
select t.id, t.status, t.batch_id, t.package_id, t.latest_terms,
  br.product_name, br.deliverables_count, br.deliverables_format, br.go_live_by,
  br.budget_ceiling_cents
from public.threads t
join public.batches ba on ba.id = t.batch_id
join public.briefs br on br.id = ba.brief_id
where t.brand_id = $1 and t.id = $2
"""
# Serializes awards per batch: the hire-target count below is read under this lock.
LOCK_BATCH = "select hires_target from public.batches where id = $1 for update"
SELECT_BATCH_TARGET = "select hires_target from public.batches where id = $1"
COUNT_HIRED = "select count(*) from public.threads where batch_id = $1 and status = 'awarded'"
SELECT_OPEN_OTHERS = """
select t.id, t.status, c.id as creator_id, c.name as creator_name, c.handle as creator_handle
from public.threads t
join public.creators c on c.id = t.creator_id
where t.brand_id = $1 and t.batch_id = $2 and t.id <> $3 and t.status = any($4::text[])
order by t.created_at, t.id
"""
INSERT_DEAL = """
insert into public.deals
  (thread_id, batch_id, brand_id, creator_id, package_id, videos, format, price_cents,
   go_live_by, conditions, addons, awarded_event_id)
values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
returning id
"""
INSERT_MILESTONE = """
insert into public.deal_milestones (deal_id, seq, title, amount_cents, due_date)
values ($1, $2, $3, $4, $5)
"""
# A deal belongs to its brand and its creator; a null id matches nothing, so a caller that
# passes neither sees nothing.
SELECT_DEAL = """
select d.id, d.thread_id, d.batch_id, d.status, d.videos, d.format, d.price_cents, d.go_live_by,
  d.conditions, d.addons, d.created_at,
  br.product_name, br.contact_email as brand_email, b.company_name as brand_name,
  c.name as creator_name, c.handle as creator_handle, c.email as creator_email
from public.deals d
join public.batches ba on ba.id = d.batch_id
join public.briefs br on br.id = ba.brief_id
join public.brands b on b.id = d.brand_id
join public.creators c on c.id = d.creator_id
where d.id = $1 and (d.brand_id = $2 or d.creator_id = $3)
"""
SELECT_MILESTONES = """
select id, seq, title, amount_cents, due_date, status
from public.deal_milestones where deal_id = $1 order by seq
"""
_LIST_COLUMNS = """
select d.id, d.thread_id, br.product_name, d.videos, d.price_cents, d.go_live_by, d.status,
  d.created_at,"""
_LIST_FROM = """
from public.deals d
join public.batches ba on ba.id = d.batch_id
join public.briefs br on br.id = ba.brief_id
"""
SELECT_BRAND_DEALS = (
    _LIST_COLUMNS
    + """ c.name as counterpart_name"""
    + _LIST_FROM
    + """join public.creators c on c.id = d.creator_id
where d.brand_id = $1
order by d.created_at desc, d.id
"""
)
SELECT_CREATOR_DEALS = (
    _LIST_COLUMNS
    + """ b.company_name as counterpart_name"""
    + _LIST_FROM
    + """join public.brands b on b.id = d.brand_id
where d.creator_id = $1
order by d.created_at desc, d.id
"""
)


async def award_context(
    conn: asyncpg.Connection, brand_id: UUID, thread_id: UUID
) -> dict[str, Any] | None:
    """The brand's thread with the brief fields an award needs (ceiling included), or None."""
    row = await conn.fetchrow(SELECT_AWARD_CONTEXT, brand_id, thread_id)
    if row is None:
        return None
    raw = row["latest_terms"]
    return dict(row) | {"latest_terms": None if raw is None else json.loads(raw)}


async def lock_batch(conn: asyncpg.Connection, batch_id: UUID) -> int:
    """Lock the batch row until the transaction ends; returns its hire target."""
    return await conn.fetchval(LOCK_BATCH, batch_id)


async def hires_target(conn: asyncpg.Connection, batch_id: UUID) -> int:
    return await conn.fetchval(SELECT_BATCH_TARGET, batch_id)


async def count_hired(conn: asyncpg.Connection, batch_id: UUID) -> int:
    return await conn.fetchval(COUNT_HIRED, batch_id)


async def open_others(
    conn: asyncpg.Connection,
    brand_id: UUID,
    batch_id: UUID,
    thread_id: UUID,
    statuses: Sequence[str],
) -> list[dict[str, Any]]:
    """The batch's other threads in these statuses, oldest first."""
    rows = await conn.fetch(SELECT_OPEN_OTHERS, brand_id, batch_id, thread_id, sorted(statuses))
    return [dict(r) for r in rows]


async def insert_deal(
    conn: asyncpg.Connection,
    *,
    thread_id: UUID,
    batch_id: UUID,
    brand_id: UUID,
    creator_id: UUID,
    package_id: UUID,
    agreed: AgreedTerms,
    awarded_event_id: int,
) -> UUID:
    return await conn.fetchval(
        INSERT_DEAL,
        thread_id,
        batch_id,
        brand_id,
        creator_id,
        package_id,
        agreed.videos,
        agreed.format,
        agreed.price_cents,
        agreed.go_live_by,
        list(agreed.conditions),
        list(agreed.addons),
        awarded_event_id,
    )


async def insert_milestones(
    conn: asyncpg.Connection, deal_id: UUID, drafts: Sequence[MilestoneDraft]
) -> None:
    await conn.executemany(
        INSERT_MILESTONE,
        [(deal_id, m.seq, m.title.strip(), m.amount_cents, m.due_date) for m in drafts],
    )


async def get_deal(
    conn: asyncpg.Connection, deal_id: UUID, *, brand_id: UUID | None, creator_id: UUID | None
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """A deal and its milestones for the brand or the creator that owns it, or None."""
    row = await conn.fetchrow(SELECT_DEAL, deal_id, brand_id, creator_id)
    if row is None:
        return None
    milestones = await conn.fetch(SELECT_MILESTONES, deal_id)
    return dict(row), [dict(m) for m in milestones]


async def brand_deals(conn: asyncpg.Connection, brand_id: UUID) -> list[dict[str, Any]]:
    return [dict(r) for r in await conn.fetch(SELECT_BRAND_DEALS, brand_id)]


async def creator_deals(conn: asyncpg.Connection, creator_id: UUID) -> list[dict[str, Any]]:
    return [dict(r) for r in await conn.fetch(SELECT_CREATOR_DEALS, creator_id)]

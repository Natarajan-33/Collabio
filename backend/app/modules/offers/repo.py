"""Offer queries. Every statement is scoped to one creator: the backend's connection bypasses
row-level security, so ownership is enforced here by `t.creator_id`.

This is the one module that reads `package_floors`, and only for the owning creator's thread.
The brief is selected without its budget ceiling and contact email, the brand without its
contact details. jsonb values come back as text.
"""

import json
from collections.abc import Collection
from typing import Any
from uuid import UUID

import asyncpg

SELECT_CREATOR_FOR_PROFILE = "select id from public.creators where profile_id = $1 limit 1"

_OFFER_COLUMNS = """
select t.id, t.status, t.latest_terms, t.latest_terms_source, t.expires_at, t.updated_at,
  t.package_id,
  br.product_name, br.deliverables_count, br.deliverables_format, br.ask_price_cents,
  br.go_live_by,
  b.id as brand_id, b.company_name as brand_name,
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
  ) as package,
  (select e.terms from public.thread_events e
   where e.thread_id = t.id and e.type = 'brand_counter_sent' and e.terms is not null
   order by e.id desc limit 1) as brand_counter"""
_OFFER_FROM = """
from public.threads t
join public.batches ba on ba.id = t.batch_id
join public.briefs br on br.id = ba.brief_id
join public.brands b on b.id = t.brand_id
join public.packages p on p.id = t.package_id
"""
SELECT_OFFERS = (
    _OFFER_COLUMNS
    + _OFFER_FROM
    + """
where t.creator_id = $1 and t.status = any($2::text[])
order by t.updated_at desc, t.id
"""
)
_DESK_EXTRAS = """,
  br.product_summary, f.floor_price_cents, d.id as deal_id
"""
SELECT_OFFER = (
    _OFFER_COLUMNS
    + _DESK_EXTRAS
    + _OFFER_FROM
    + """left join public.package_floors f on f.package_id = t.package_id
left join public.deals d on d.thread_id = t.id
where t.creator_id = $1 and t.id = $2 and t.status = any($3::text[])
"""
)
SELECT_STATUS_FOR_UPDATE = "select status from public.threads where id = $1 for update"
COUNT_BY_STATUS = """
select status, count(*) as n from public.threads
where creator_id = $1 and status = any($2::text[])
group by status
"""
SELECT_NEWEST_BRAND_NOTE = """
select payload from public.thread_events
where thread_id = $1 and creator_id = $2 and type = 'brand_counter_sent'
order by id desc limit 1
"""
# `failed` and `retried` are the brand side's plumbing, not part of the creator's story.
SELECT_EVENTS = """
select id, thread_id, type, actor, created_at, payload, terms
from public.thread_events
where creator_id = $1 and thread_id = $2 and type <> all('{failed,retried}'::text[])
order by id
"""
SELECT_TRANSCRIPTS = """
select tr.id, tr.kind, tr.created_at, tr.subject, tr.body_text, tr.turns, tr.summary
from public.transcripts tr
join public.threads t on t.id = tr.thread_id
where t.creator_id = $1 and tr.thread_id = $2
order by tr.created_at desc, tr.id
"""


def _loads(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _offer(row: asyncpg.Record) -> dict[str, Any]:
    return dict(row) | {
        "latest_terms": _loads(row["latest_terms"]),
        "package": _loads(row["package"]),
        "brand_counter": _loads(row["brand_counter"]),
    }


async def creator_for_profile(conn: asyncpg.Connection, profile_id: UUID) -> UUID | None:
    """The signed-in user's creator id, or None when onboarding never created one."""
    return await conn.fetchval(SELECT_CREATOR_FOR_PROFILE, profile_id)


async def list_offers(
    conn: asyncpg.Connection, creator_id: UUID, statuses: Collection[str]
) -> list[dict[str, Any]]:
    """The creator's offers in these statuses, newest activity first."""
    return [_offer(r) for r in await conn.fetch(SELECT_OFFERS, creator_id, sorted(statuses))]


async def get_offer(
    conn: asyncpg.Connection, creator_id: UUID, thread_id: UUID, statuses: Collection[str]
) -> dict[str, Any] | None:
    """One of the creator's offers with its own package floor and deal id, or None."""
    row = await conn.fetchrow(SELECT_OFFER, creator_id, thread_id, sorted(statuses))
    return None if row is None else _offer(row)


async def status_counts(
    conn: asyncpg.Connection, creator_id: UUID, statuses: Collection[str]
) -> dict[str, int]:
    rows = await conn.fetch(COUNT_BY_STATUS, creator_id, sorted(statuses))
    return {r["status"]: r["n"] for r in rows}


async def newest_brand_note(
    conn: asyncpg.Connection, creator_id: UUID, thread_id: UUID
) -> str | None:
    """The note of the brand's newest counter, or None."""
    raw = await conn.fetchval(SELECT_NEWEST_BRAND_NOTE, thread_id, creator_id)
    return None if raw is None else _loads(raw).get("note")


async def offer_events(
    conn: asyncpg.Connection, creator_id: UUID, thread_id: UUID
) -> list[dict[str, Any]]:
    rows = await conn.fetch(SELECT_EVENTS, creator_id, thread_id)
    return [dict(r) | {"payload": _loads(r["payload"]), "terms": _loads(r["terms"])} for r in rows]


async def offer_transcripts(
    conn: asyncpg.Connection, creator_id: UUID, thread_id: UUID
) -> list[dict[str, Any]]:
    """The offer's transcripts, newest first."""
    rows = await conn.fetch(SELECT_TRANSCRIPTS, creator_id, thread_id)
    return [dict(r) | {"turns": _loads(r["turns"])} for r in rows]


async def lock_status(conn: asyncpg.Connection, thread_id: UUID) -> str:
    """Lock the thread row until the caller's transaction ends and return its status."""
    return await conn.fetchval(SELECT_STATUS_FOR_UPDATE, thread_id)

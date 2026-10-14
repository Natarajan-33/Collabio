"""Brief queries. Every statement is scoped to one brand: the backend's connection bypasses
row-level security, so ownership is enforced here by `brand_id`.

Brief rows are plain dicts holding every column the API needs, including the brand-only
`budget_ceiling_cents`. The preview query reads creators' phone and opt-in flags for the
service's channel decisions; the service must never return them.
"""

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import asyncpg

from app.schemas.briefs import BriefFields

SELECT_BRAND_FOR_PROFILE = """
select id, company_name, contact_email
from public.brands where profile_id = $1 order by id limit 1
"""
SELECT_BRAND = "select id, company_name, contact_email from public.brands where id = $1"
SELECT_FIRST_PRODUCT = """
select id, name, summary from public.products where brand_id = $1 order by id limit 1
"""
SELECT_LISTED_CREATORS = """
select c.id
from public.creators c
where c.id = any($1::uuid[])
  and exists (
    select 1 from public.packages p where p.creator_id = c.id and p.status = 'published'
  )
"""

SELECT_UNREGISTERED = """
select c.id
from unnest($1::uuid[]) with ordinality as wanted (id, position)
join public.creators c on c.id = wanted.id
where c.profile_id is null
order by wanted.position
"""

INSERT_BRIEF = """
insert into public.briefs
  (brand_id, product_id, brand_name, product_name, product_summary, contact_email, creator_ids)
values ($1, $2, $3, $4, $5, $6, $7)
returning id
"""

INSERT_BATCH = """
insert into public.batches (brief_id, brand_id, follow_up_policy, brief_embedding, hires_target)
values ($1, $2, $3, $4, $5)
returning id
"""
# `next_action_at` stays null (due now) unless the thread is held back with 'infinity'.
INSERT_THREAD = """
insert into public.threads
  (batch_id, brand_id, creator_id, package_id, channel_plan, reply_token, next_action_at)
values ($1, $2, $3, $4, $5, $6, case when $7 then 'infinity'::timestamptz end)
returning id
"""
MARK_LAUNCHED = "update public.briefs set status = 'launched', approved_at = now() where id = $1"

BRIEF_COLUMNS = ", ".join(f"b.{name}" for name in BriefFields.model_fields)
SELECT_BRIEF = f"""
select b.id, b.status, b.creator_ids, b.approved_at, ba.id as batch_id, {BRIEF_COLUMNS}
from public.briefs b
left join public.batches ba on ba.brief_id = b.id
where b.brand_id = $1 and b.id = $2
"""
# Locks the brief row until the transaction ends, so concurrent patches cannot interleave.
LOCK_BRIEF = " for update of b"

# Columns `update_brief` may set; the caller's keys are checked against this list because
# they become part of the statement.
PATCHABLE = (*BriefFields.model_fields, "intake_conversation_id", "status")

# One row per requested creator, in the order of `$1`, with the published packages as a JSON
# array carrying every `PackageTerms` field. `phone`, `phone_opt_in` and `contact_opt_out`
# are for the channel decision only.
SELECT_PREVIEW = """
select
  c.id, c.name, c.handle, c.phone, c.phone_opt_in, c.contact_opt_out,
  coalesce(
    (
      select json_agg(
        json_build_object(
          'id', p.id,
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
        )
        order by p.base_price_cents, p.name, p.id
      )
      from public.packages p
      where p.creator_id = c.id and p.status = 'published'
    ),
    '[]'::json
  ) as packages
from unnest($1::uuid[]) with ordinality as wanted (id, position)
join public.creators c on c.id = wanted.id
order by wanted.position
"""


async def brand_for_profile(conn: asyncpg.Connection, profile_id: UUID) -> dict[str, Any] | None:
    """The signed-in user's brand (id, company_name, contact_email), or None."""
    row = await conn.fetchrow(SELECT_BRAND_FOR_PROFILE, profile_id)
    return None if row is None else dict(row)


async def brand_by_id(conn: asyncpg.Connection, brand_id: UUID) -> dict[str, Any]:
    """A brand's id, company_name and contact_email; the id must be a known brand's."""
    row = await conn.fetchrow(SELECT_BRAND, brand_id)
    assert row is not None
    return dict(row)


async def first_product(conn: asyncpg.Connection, brand_id: UUID) -> dict[str, Any] | None:
    row = await conn.fetchrow(SELECT_FIRST_PRODUCT, brand_id)
    return None if row is None else dict(row)


async def listed_creator_ids(conn: asyncpg.Connection, creator_ids: Sequence[UUID]) -> set[UUID]:
    """The ids among `creator_ids` that are creators with at least one published package."""
    rows = await conn.fetch(SELECT_LISTED_CREATORS, list(creator_ids))
    return {row["id"] for row in rows}


async def unregistered_creator_ids(
    conn: asyncpg.Connection, creator_ids: Sequence[UUID]
) -> list[UUID]:
    """The ids among `creator_ids` whose creator has no account (`profile_id is null`), in order."""
    rows = await conn.fetch(SELECT_UNREGISTERED, list(creator_ids))
    return [row["id"] for row in rows]


async def insert_brief(
    conn: asyncpg.Connection,
    *,
    brand_id: UUID,
    product_id: UUID | None,
    brand_name: str,
    product_name: str | None,
    product_summary: str | None,
    contact_email: str | None,
    creator_ids: Sequence[UUID],
) -> UUID:
    return await conn.fetchval(
        INSERT_BRIEF,
        brand_id,
        product_id,
        brand_name,
        product_name,
        product_summary,
        contact_email,
        list(creator_ids),
    )


async def get_brief(
    conn: asyncpg.Connection, brand_id: UUID, brief_id: UUID, *, lock: bool = False
) -> dict[str, Any] | None:
    """The brand's brief, or None when it does not exist or belongs to another brand."""
    row = await conn.fetchrow(SELECT_BRIEF + (LOCK_BRIEF if lock else ""), brand_id, brief_id)
    return None if row is None else dict(row)


async def update_brief(conn: asyncpg.Connection, brief_id: UUID, values: dict[str, Any]) -> None:
    """Set the given columns on a brief."""
    unknown = set(values) - set(PATCHABLE)
    if unknown:
        raise ValueError(f"not patchable: {sorted(unknown)}")
    if not values:
        return
    assignments = ", ".join(f"{column} = ${i}" for i, column in enumerate(values, start=2))
    await conn.execute(
        f"update public.briefs set {assignments} where id = $1", brief_id, *values.values()
    )


async def preview_rows(
    conn: asyncpg.Connection, creator_ids: Sequence[UUID]
) -> list[dict[str, Any]]:
    """Creators in `creator_ids` order with `packages`, their published packages as dicts
    (cheapest first). Creators that no longer exist are skipped."""
    rows = await conn.fetch(SELECT_PREVIEW, list(creator_ids))
    return [dict(row) | {"packages": json.loads(row["packages"])} for row in rows]


async def insert_batch(
    conn: asyncpg.Connection,
    *,
    brief_id: UUID,
    brand_id: UUID,
    follow_up_policy: str,
    embedding: list[float] | None,
    hires_target: int,
) -> UUID:
    """The brief's batch; `unique (brief_id)` makes a second one fail."""
    return await conn.fetchval(
        INSERT_BATCH, brief_id, brand_id, follow_up_policy, embedding, hires_target
    )


async def insert_thread(
    conn: asyncpg.Connection,
    *,
    batch_id: UUID,
    brand_id: UUID,
    creator_id: UUID,
    package_id: UUID,
    channel_plan: str,
    reply_token: str,
    hold: bool,
) -> UUID:
    """A queued thread. `hold` parks it at `next_action_at = 'infinity'` so no worker claims it."""
    return await conn.fetchval(
        INSERT_THREAD,
        batch_id,
        brand_id,
        creator_id,
        package_id,
        channel_plan,
        reply_token,
        hold,
    )


async def mark_launched(conn: asyncpg.Connection, brief_id: UUID) -> None:
    await conn.execute(MARK_LAUNCHED, brief_id)

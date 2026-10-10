"""Creator package queries. Every statement is scoped to one creator: the backend's
connection bypasses row-level security, so ownership is enforced here by `creator_id`.

Package rows are plain dicts with `addons` and `extras` decoded from jsonb and the
private `floor_price_cents` (None when no floor is set).
"""

import json
from typing import Any
from uuid import UUID

import asyncpg

from app.schemas.packages import PackageTerms

SELECT_CREATOR = "select id, name, bio, niches from public.creators where profile_id = $1"
SELECT_EMBEDDING_HASH = "select embedding_text_hash from public.creators where id = $1"
UPDATE_EMBEDDING = """
update public.creators set embedding = $2, embedding_text_hash = $3 where id = $1
"""

# Cheapest first, like the creator's card in discovery.
SELECT_PACKAGES = """
select p.id, p.name, p.content_type, p.niche, p.volume_count, p.volume_basis,
       p.base_price_cents, p.currency, p.included, p.freebies, p.addons, p.extras,
       p.slots_per_month, p.lead_time_days, p.preferred_channel, p.status,
       f.floor_price_cents
from public.packages p
left join public.package_floors f on f.package_id = p.id
where p.creator_id = $1
"""
LIST_ORDER = " order by p.base_price_cents, p.name, p.id"
ONE_PACKAGE = " and p.id = $2"
# Locks the package row until the caller's transaction ends, so edits, publishing and
# floor changes to one package cannot interleave.
LOCK_PACKAGE = " for update of p"

INSERT_PACKAGE = """
insert into public.packages
  (creator_id, name, content_type, niche, volume_count, volume_basis, base_price_cents,
   currency, included, freebies, addons, extras, slots_per_month, lead_time_days,
   preferred_channel)
values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
returning id
"""
# packages.updated_at has no trigger, so every update sets it.
UPDATE_PACKAGE = """
update public.packages set
  name = $3, content_type = $4, niche = $5, volume_count = $6, volume_basis = $7,
  base_price_cents = $8, currency = $9, included = $10, freebies = $11, addons = $12,
  extras = $13, slots_per_month = $14, lead_time_days = $15, preferred_channel = $16,
  updated_at = now()
where creator_id = $1 and id = $2
"""
PUBLISH_PACKAGE = """
update public.packages set status = 'published', updated_at = now()
where creator_id = $1 and id = $2
"""
UPSERT_FLOOR = """
insert into public.package_floors (package_id, floor_price_cents) values ($1, $2)
on conflict (package_id) do update set floor_price_cents = excluded.floor_price_cents
"""


def _row(record: asyncpg.Record) -> dict[str, Any]:
    return dict(record) | {
        "addons": json.loads(record["addons"]),
        "extras": json.loads(record["extras"]),
    }


def _terms_values(terms: PackageTerms) -> tuple[Any, ...]:
    """The terms in the column order of INSERT_PACKAGE after `creator_id`."""
    return (
        terms.name,
        terms.content_type,
        terms.niche,
        terms.volume_count,
        terms.volume_basis,
        terms.base_price_cents,
        terms.currency,
        terms.included,
        terms.freebies,
        json.dumps([addon.model_dump() for addon in terms.addons]),
        json.dumps([extra.model_dump() for extra in terms.extras]),
        terms.slots_per_month,
        terms.lead_time_days,
        terms.preferred_channel,
    )


async def creator_for_profile(conn: asyncpg.Connection, profile_id: UUID) -> dict[str, Any] | None:
    """The creator row (id, name, bio, niches) of a signed-in user, or None."""
    row = await conn.fetchrow(SELECT_CREATOR, profile_id)
    return None if row is None else dict(row)


async def list_packages(conn: asyncpg.Connection, creator_id: UUID) -> list[dict[str, Any]]:
    rows = await conn.fetch(SELECT_PACKAGES + LIST_ORDER, creator_id)
    return [_row(row) for row in rows]


async def get_package(
    conn: asyncpg.Connection, creator_id: UUID, package_id: UUID, *, lock: bool = False
) -> dict[str, Any] | None:
    """The creator's package, or None when it does not exist or belongs to someone else.
    With `lock`, the row stays locked until the surrounding transaction ends."""
    sql = SELECT_PACKAGES + ONE_PACKAGE + (LOCK_PACKAGE if lock else "")
    row = await conn.fetchrow(sql, creator_id, package_id)
    return None if row is None else _row(row)


async def insert_package(conn: asyncpg.Connection, creator_id: UUID, terms: PackageTerms) -> UUID:
    """Save a new package as a draft."""
    return await conn.fetchval(INSERT_PACKAGE, creator_id, *_terms_values(terms))


async def update_package(
    conn: asyncpg.Connection, creator_id: UUID, package_id: UUID, terms: PackageTerms
) -> None:
    await conn.execute(UPDATE_PACKAGE, creator_id, package_id, *_terms_values(terms))


async def publish_package(conn: asyncpg.Connection, creator_id: UUID, package_id: UUID) -> None:
    await conn.execute(PUBLISH_PACKAGE, creator_id, package_id)


async def set_floor(conn: asyncpg.Connection, package_id: UUID, floor_price_cents: int) -> None:
    await conn.execute(UPSERT_FLOOR, package_id, floor_price_cents)


async def embedding_hash(conn: asyncpg.Connection, creator_id: UUID) -> str | None:
    """Hash of the document the creator's stored embedding was made from, if any."""
    return await conn.fetchval(SELECT_EMBEDDING_HASH, creator_id)


async def save_embedding(
    conn: asyncpg.Connection, creator_id: UUID, embedding: list[float], digest: str
) -> None:
    await conn.execute(UPDATE_EMBEDDING, creator_id, embedding, digest)

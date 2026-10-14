"""Discovery queries: which creators match a search, and the card data for them.

The backend's connection bypasses row-level security, so these statements select
public columns only: never a creator's contact fields, embedding or package floors.
"""

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import asyncpg

from app.schemas.discovery import SearchFilters

# `match_creators` applies every filter and ranks: by distance to the embedding when
# one is given, otherwise by followers.
MATCH_CREATORS = """
select creator_id
from public.match_creators(
  query_embedding => $1,
  max_price_cents => $2,
  content_types => $3,
  niches => $4,
  region => $5,
  min_followers => $6,
  match_limit => $7,
  registered_only => $8
)
"""

# One row per requested creator, in the order of `$1`, each with its published packages
# (cheapest first) as a JSON array. `jsonb` addons nest as arrays, not strings.
SELECT_CARDS = """
select
  c.id, c.handle, c.name, c.niches, c.region, c.followers, c.engagement_rate,
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
          'addons', p.addons,
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
where (not $2 or c.profile_id is not null)
order by wanted.position
"""


async def match_creator_ids(
    conn: asyncpg.Connection,
    *,
    embedding: list[float] | None,
    filters: SearchFilters,
    limit: int,
    registered_only: bool = False,
) -> list[UUID]:
    """Ids of the best matches, best first. Creators without an embedding rank last.
    `registered_only` leaves out creators with no account (`profile_id is null`)."""
    rows = await conn.fetch(
        MATCH_CREATORS,
        embedding,
        filters.max_price_cents,
        filters.content_types,
        filters.niches,
        filters.region,
        filters.min_followers,
        limit,
        registered_only,
    )
    return [row["creator_id"] for row in rows]


async def fetch_cards(
    conn: asyncpg.Connection, creator_ids: Sequence[UUID], *, registered_only: bool = False
) -> list[dict[str, Any]]:
    """Card data for `creator_ids`, in that order; unknown ids are skipped.

    Each dict has the creator's public columns plus `packages`, a list of dicts for the
    published packages only. A creator with none has an empty list. `registered_only`
    skips creators with no account.
    """
    rows = await conn.fetch(SELECT_CARDS, list(creator_ids), registered_only)
    return [dict(row) | {"packages": json.loads(row["packages"])} for row in rows]

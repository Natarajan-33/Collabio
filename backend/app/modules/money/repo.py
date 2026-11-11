"""Data access for M4 money. Every query takes a connection; callers own transactions."""

import json
from typing import Any
from uuid import UUID

import asyncpg


async def brand_deal(conn: asyncpg.Connection, deal_id: UUID, brand_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        "select * from public.deals where id = $1 and brand_id = $2", deal_id, brand_id
    )
    return None if row is None else dict(row)


async def party_deal(
    conn: asyncpg.Connection, deal_id: UUID, *, brand_id: UUID | None, creator_id: UUID | None
) -> dict | None:
    row = await conn.fetchrow(
        "select * from public.deals where id = $1 and (brand_id = $2 or creator_id = $3)",
        deal_id,
        brand_id,
        creator_id,
    )
    return None if row is None else dict(row)


async def milestones(conn: asyncpg.Connection, deal_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "select * from public.deal_milestones where deal_id = $1 order by seq", deal_id
    )
    return [dict(r) for r in rows]


async def bonus_terms(conn: asyncpg.Connection, deal_id: UUID) -> dict | None:
    row = await conn.fetchrow("select * from public.deal_bonus_terms where deal_id = $1", deal_id)
    if row is None:
        return None
    out = dict(row)
    if isinstance(out["terms"], str):
        out["terms"] = json.loads(out["terms"])
    return out


async def upsert_bonus_terms(
    conn: asyncpg.Connection,
    deal_id: UUID,
    source_text: str,
    terms: dict[str, Any],
    max_bonus_per_video_cents: int,
) -> None:
    await conn.execute(
        "insert into public.deal_bonus_terms (deal_id, source_text, terms, max_bonus_per_video_cents)"
        " values ($1, $2, $3::jsonb, $4)"
        " on conflict (deal_id) do update set source_text = excluded.source_text,"
        " terms = excluded.terms, max_bonus_per_video_cents = excluded.max_bonus_per_video_cents,"
        " created_at = now()",
        deal_id,
        source_text,
        json.dumps(terms),
        max_bonus_per_video_cents,
    )


async def set_auto_approve_limit(conn: asyncpg.Connection, brand_id: UUID, cents: int) -> None:
    await conn.execute(
        "update public.brands set auto_approve_limit_cents = $2 where id = $1", brand_id, cents
    )


async def auto_approve_limit(conn: asyncpg.Connection, brand_id: UUID) -> int:
    return await conn.fetchval(
        "select auto_approve_limit_cents from public.brands where id = $1", brand_id
    )

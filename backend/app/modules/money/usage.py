"""Daily usage counters behind the hackathon demo caps."""

from uuid import UUID

from fastapi import HTTPException, status

from app.adapters.db import Database
from app.config import Settings
from app.core.caps import cap_for

UPSERT = """
insert into public.usage_counters (user_id, day, kind, count)
values ($1, current_date, $2, 1)
on conflict (user_id, day, kind) do update set count = public.usage_counters.count + 1
returning count
"""


async def consume(db: Database, user_id: UUID, kind: str, settings: Settings) -> None:
    """Count one use of `kind` today; 429 `demo_cap` once over the cap. No-op outside
    hackathon mode."""
    if not settings.hackathon_mode:
        return
    limit = cap_for(kind)
    async with db.acquire() as conn:
        count = await conn.fetchval(UPSERT, user_id, kind)
    if count > limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "demo_cap")

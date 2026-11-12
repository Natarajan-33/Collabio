"""Daily usage counters behind the hackathon demo caps."""

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException, status

from app.adapters.db import Database
from app.config import Settings
from app.core.caps import cap_for

UPSERT = """
insert into public.usage_counters (user_id, day, kind, count)
values ($1, current_date, $2, $3)
on conflict (user_id, day, kind) do update set count = public.usage_counters.count + $3
returning count
"""


def client_ip(request: Any) -> str:
    """The visitor's address: the rightmost X-Forwarded-For entry (appended by Render's proxy;
    entries to its left are client-supplied), else the socket peer."""
    forwarded = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if parts:
        return parts[-1]
    return request.client.host if request.client else "unknown"


def ip_key(ip: str) -> UUID:
    """A stable pseudo user id for a visitor's address (usage_counters keys on a uuid)."""
    return uuid5(NAMESPACE_URL, f"collabio-visitor:{ip}")


async def consume(
    db: Database,
    user_id: UUID,
    kind: str,
    settings: Settings,
    *,
    amount: int = 1,
    ip: str | None = None,
) -> None:
    """Count `amount` uses of `kind` today; 429 `demo_cap` once over the cap. With `ip`, the
    visitor's own sub-cap (`<kind>_ip`) is charged too: every judge shares the same demo
    personas, so per-user caps are global and one visitor must not spend them all.
    No-op outside hackathon mode."""
    if not settings.hackathon_mode:
        return
    async with db.acquire() as conn:
        count = await conn.fetchval(UPSERT, user_id, kind, amount)
        ip_count = await conn.fetchval(UPSERT, ip_key(ip), kind, amount) if ip else None
    if count > cap_for(kind) or (ip_count is not None and ip_count > cap_for(f"{kind}_ip")):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "demo_cap")

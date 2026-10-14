"""The offer expiry sweep: `awaiting_reply` offers whose clock has run out become `no_response`.

`threads.expires_at` is set by SQL whenever a thread enters `awaiting_reply` (Ruling 1), so the
sweep only has to look. Each thread is moved in its own transaction, with its row locked and
its status and expiry checked again: one that moved on since the sweep chose it, or whose
transition fails, never stops the others. A late reply still reopens a `no_response` thread.
"""

import asyncio
import logging
from uuid import UUID

from app.adapters.db import Database
from app.modules.threads import repo
from app.modules.threads.repo import StaleThread

logger = logging.getLogger(__name__)

BATCH = 100

SELECT_DUE = """
select id from public.threads
where status = 'awaiting_reply' and expires_at < now()
  and ($2::uuid is null or batch_id = $2::uuid)
order by expires_at, id
limit $1
"""
# Rechecked under a row lock; a thread someone else holds is theirs to move.
LOCK_DUE = """
select id from public.threads
where id = $1 and status = 'awaiting_reply' and expires_at < now()
for update skip locked
"""


async def due_offers(db: Database, *, limit: int, batch_id: UUID | None = None) -> list[UUID]:
    """Ids of up to `limit` lapsed offers, the longest overdue first."""
    async with db.acquire() as conn:
        rows = await conn.fetch(SELECT_DUE, limit, batch_id)
    return [row["id"] for row in rows]


async def _expire(db: Database, thread_id: UUID) -> bool:
    """Move one lapsed offer to `no_response`; False when it is no longer due."""
    async with db.transaction() as conn:
        if await conn.fetchval(LOCK_DUE, thread_id) is None:
            return False
        thread = await repo.load_ref(conn, thread_id)
        if thread is None:
            return False
        try:
            await repo.apply_event(
                conn,
                thread,
                expected={"awaiting_reply"},
                target="no_response",
                type="offer_expired",
                actor="system",
            )
        except StaleThread:
            return False
        return True


async def expire_offers(db: Database, *, limit: int = BATCH, batch_id: UUID | None = None) -> int:
    """Move up to `limit` lapsed offers to `no_response`; how many moved.

    `batch_id` limits the sweep to one batch (tests share a database with real data).
    """
    moved = 0
    for thread_id in await due_offers(db, limit=limit, batch_id=batch_id):
        try:
            moved += await _expire(db, thread_id)
        except Exception:
            logger.exception("Expiring offer on thread %s failed", thread_id)
    if moved:
        logger.info("Expiry sweep: %d offers lapsed", moved)
    return moved


async def expiry_loop(db: Database, *, interval_s: float = 60.0) -> None:
    """Sweep until cancelled.

    A full batch means more may be waiting, so the loop goes again at once; otherwise it
    sleeps `interval_s`. A failing pass is logged and the loop goes on; cancellation propagates.
    """
    while True:
        moved = 0
        try:
            moved = await expire_offers(db)
        except Exception:
            logger.exception("Expiry sweep failed")
        if moved < BATCH:
            await asyncio.sleep(interval_s)

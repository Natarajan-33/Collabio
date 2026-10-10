"""The restart sweep: threads a dead process left half-done.

A `drafting` thread is safe to resume (the draft and the Resend idempotency key are stable
per attempt, so nobody is emailed twice). A `calling` thread with no conversation id never
reached ElevenLabs as far as we know; dialing again could ring a creator twice, so it is
failed and a person decides. Calls with a conversation id belong to the call watcher.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.adapters.db import Database
from app.modules.threads.repo import StaleThread, fail_thread, transition

logger = logging.getLogger(__name__)

SELECT_STALE = """
select id, status from public.threads
where updated_at < now() - $1::interval
  and (status = 'drafting' or (status = 'calling' and call_conversation_id is null))
  and ($2::uuid is null or batch_id = $2::uuid)
order by created_at, id
"""

RESUMED = "Resumed after a restart"
CALL_INTERRUPTED = "Interrupted before the call was placed. Retry to call again."


@dataclass(frozen=True)
class SweepResult:
    requeued: int
    failed: int


async def sweep_stuck(
    db: Database,
    *,
    stale_after: timedelta = timedelta(minutes=2),
    batch_id: UUID | None = None,
) -> SweepResult:
    """Requeue stale `drafting` threads and fail stale `calling` ones with no conversation.

    `batch_id` limits the sweep to one batch (tests share a database with real data).
    """
    async with db.acquire() as conn:
        stale = await conn.fetch(SELECT_STALE, stale_after, batch_id)
    requeued = failed = 0
    for row in stale:
        thread_id, status = row["id"], row["status"]
        try:
            async with db.transaction() as conn:
                if status == "drafting":
                    await transition(
                        conn,
                        thread_id,
                        expected={"drafting"},
                        target="queued",
                        last_error=RESUMED,
                    )
                    requeued += 1
                else:
                    await fail_thread(conn, thread_id, CALL_INTERRUPTED)
                    failed += 1
        except StaleThread:
            continue  # someone moved it first
        except Exception:
            logger.exception("Sweeping thread %s failed", thread_id)
    if requeued or failed:
        logger.info("Restart sweep: requeued %d, failed %d", requeued, failed)
    return SweepResult(requeued=requeued, failed=failed)

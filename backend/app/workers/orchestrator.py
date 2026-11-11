"""The launch orchestrator: claims queued threads and hands each to its channel's handler.

Claims use `FOR UPDATE SKIP LOCKED`, so any number of orchestrators (or processes) can run
without taking the same thread twice. A handler that raises fails only its own thread; the
orchestrator and the other threads carry on.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID

from app.adapters.db import Database
from app.modules.threads.repo import claim_queued, fail_thread

logger = logging.getLogger(__name__)

Handler = Callable[[UUID], Awaitable[None]]

PROCESSING_FAILED = "Something went wrong while processing. Retry to try again."


def handler_key(channel_plan: str, *, email_only: bool = False) -> str:
    """`email_then_call` behaves as `email` in M2: the call step is a follow-up (Ruling 16).
    `email_only` (hackathon mode) routes every plan to email so no phone call is ever placed."""
    if email_only or channel_plan == "email_then_call":
        return "email"
    return channel_plan


class Orchestrator:
    """`handlers` maps a channel (`email`, `call`) to the coroutine that works a claimed
    thread. `batch_id` restricts claims to one batch and ignores `next_action_at` (tests)."""

    def __init__(
        self,
        db: Database,
        handlers: Mapping[str, Handler],
        *,
        concurrency: int = 5,
        poll_seconds: float = 1.0,
        batch_id: UUID | None = None,
        email_only: bool = False,
    ) -> None:
        self._db = db
        self._email_only = email_only
        self._handlers = handlers
        self._concurrency = concurrency
        self._poll_seconds = poll_seconds
        self._batch_id = batch_id
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Look for work now instead of at the next poll."""
        self._wake.set()

    async def _claim(self, limit: int) -> list[tuple[UUID, str]]:
        async with self._db.acquire() as conn:
            claimed = await claim_queued(conn, limit=limit, batch_id=self._batch_id)
        return [(c.id, c.channel_plan) for c in claimed]

    async def process_once(self) -> int:
        """Claim up to `concurrency` threads, work them concurrently, and return how many."""
        claimed = await self._claim(self._concurrency)
        await asyncio.gather(*(self._run_one(thread_id, plan) for thread_id, plan in claimed))
        return len(claimed)

    async def run(self) -> None:
        """Work threads until cancelled: claim the free slots, then wait for a wake-up, a
        finished thread or the next poll."""
        running: set[asyncio.Task[None]] = set()
        try:
            while True:
                self._wake.clear()  # before the claim, so a wake during it is not lost
                free = self._concurrency - len(running)
                if free > 0:
                    try:
                        claimed = await self._claim(free)
                    except Exception:
                        logger.exception("Claiming queued threads failed")
                        claimed = []
                    for thread_id, plan in claimed:
                        task = asyncio.create_task(self._run_one(thread_id, plan))
                        running.add(task)
                        task.add_done_callback(running.discard)
                waker = asyncio.ensure_future(self._wake.wait())
                try:
                    await asyncio.wait(
                        {waker, *running},
                        timeout=self._poll_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    waker.cancel()
        finally:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)

    async def _run_one(self, thread_id: UUID, plan: str) -> None:
        try:
            handler = self._handlers.get(handler_key(plan, email_only=self._email_only))
            if handler is None:
                raise LookupError(f"No handler for channel plan {plan!r}")
            await handler(thread_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Processing thread %s failed", thread_id)
            try:
                async with self._db.transaction() as conn:
                    await fail_thread(conn, thread_id, PROCESSING_FAILED)
            except Exception:
                logger.exception("Could not record the failure of thread %s", thread_id)

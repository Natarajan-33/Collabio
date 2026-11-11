"""Dispatches settlement runs off the request path.

In-process by default (one asyncio task per submission); Render Workflows when enabled
(Task 16). Tests await `wait_all()`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def start(settle: Callable[[UUID], Awaitable[object]], submission_id: UUID) -> None:
    async def run() -> None:
        try:
            await settle(submission_id)
        except Exception:
            logger.exception("settlement run failed for submission %s", submission_id)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def wait_all() -> None:
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)

"""Dispatches settlement runs off the request path.

With `RENDER_WORKFLOWS_ENABLED=1` a run is started as the `settle_submission` task of the
Render Workflows service (`backend/workflows/settlement.py`); on any error starting it, or when
the flag is off, it runs in-process (one asyncio task per submission). Runs are idempotent per
submission, so a run that both starts on Render and falls back cannot pay twice. Tests await
`wait_all()`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.config import Settings

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()

Trigger = Callable[[Settings, UUID], Awaitable[object]]


async def trigger_render(settings: Settings, submission_id: UUID) -> str:
    """Start `settle_submission` on Render Workflows; returns the task run id."""
    from render import RenderAsync  # imported lazily: only needed when enabled

    client = RenderAsync(token=settings.render_api_key)
    run = await client.workflows.start_task(
        task_identifier=f"{settings.render_workflow_slug}/settle_submission",
        input_data=[str(submission_id)],
    )
    return run.id


def start(
    settle: Callable[[UUID], Awaitable[object]],
    submission_id: UUID,
    settings: Settings | None = None,
    *,
    trigger: Trigger = trigger_render,
) -> None:
    async def run() -> None:
        if settings is not None and settings.render_workflows_enabled:
            try:
                run_id = await trigger(settings, submission_id)
                logger.info("settlement for %s started on Render (%s)", submission_id, run_id)
                return
            except Exception:
                logger.warning(
                    "Render Workflows trigger failed for %s; settling in-process",
                    submission_id,
                    exc_info=True,
                )
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

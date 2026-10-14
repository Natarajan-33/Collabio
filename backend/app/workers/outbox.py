"""The outbox sender loop: deliver due notification emails every few seconds."""

import asyncio
import logging
from collections.abc import Callable

from app.adapters.db import Database
from app.adapters.email import EmailPort
from app.adapters.gemini import GeminiPort
from app.config import Settings
from app.modules.notify.sender import send_due

logger = logging.getLogger(__name__)

BATCH = 10


async def outbox_loop(
    db: Database,
    *,
    email: Callable[[], EmailPort],
    gemini: GeminiPort | None,
    settings: Settings,
    interval_s: float = 5.0,
) -> None:
    """Send due rows until cancelled.

    A full batch means more may be waiting, so the loop goes again at once; otherwise it
    sleeps `interval_s`. A failing pass is logged and the loop goes on; cancellation
    propagates.
    """
    while True:
        processed = 0
        try:
            processed = await send_due(
                db, email=email, gemini=gemini, settings=settings, limit=BATCH
            )
        except Exception:
            logger.exception("Outbox pass failed")
        if processed < BATCH:
            await asyncio.sleep(interval_s)

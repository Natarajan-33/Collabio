"""Starting and stopping the background workers with the app."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI

from app.adapters.db import Database
from app.adapters.elevenlabs import ConversationSnapshot, ElevenLabsClient, ElevenLabsPort
from app.adapters.email import EmailPort, ResendClient
from app.adapters.gemini import GeminiClient, GeminiPort
from app.config import Settings
from app.modules.negotiation.calls import start_call
from app.modules.outreach.service import send_outreach
from app.workers.call_watcher import CallWatcher
from app.workers.orchestrator import Handler, Orchestrator
from app.workers.sweep import sweep_loop, sweep_stuck

logger = logging.getLogger(__name__)


@dataclass
class Workers:
    """What `start_workers` leaves running on `app.state.workers`."""

    orchestrator: Orchestrator
    tasks: list[asyncio.Task[None]]
    gemini: GeminiPort | None
    elevenlabs: ElevenLabsPort | None


def _email_handler(db: Database, gemini: GeminiPort | None, settings: Settings) -> Handler:
    resend: EmailPort | None = None

    def email() -> EmailPort:
        """Built on first use, so reserved-address threads work without a Resend key."""
        nonlocal resend
        if resend is None:
            resend = ResendClient(settings)  # ValueError without RESEND_API_KEY
        return resend

    async def handle(thread_id: UUID) -> None:
        await send_outreach(
            db,
            gemini=gemini,
            email=email,
            settings=settings,
            thread_id=thread_id,
            today=datetime.now(UTC).date(),
        )

    return handle


def _call_handler(db: Database, elevenlabs: ElevenLabsPort | None, settings: Settings) -> Handler:
    async def handle(thread_id: UUID) -> None:
        await start_call(
            db,
            elevenlabs=elevenlabs,
            settings=settings,
            thread_id=thread_id,
            today=datetime.now(UTC).date(),
        )

    return handle


async def _complete_call_placeholder(conversation_id: str, snapshot: ConversationSnapshot) -> None:
    """Replaced by the real call completion in Task 13."""
    logger.info("call completion arrives in Task 13 (conversation %s)", conversation_id)


async def start_workers(app: FastAPI, settings: Settings) -> None:
    """Build the ports once, sweep what a previous process left half-done, and start the
    orchestrator. Needs `app.state.db`."""
    db: Database = app.state.db
    gemini = GeminiClient(settings) if settings.gemini_api_key else None
    elevenlabs = ElevenLabsClient(settings) if settings.elevenlabs_api_key else None
    orchestrator = Orchestrator(
        db,
        {
            "email": _email_handler(db, gemini, settings),
            "call": _call_handler(db, elevenlabs, settings),
        },
    )
    try:
        await sweep_stuck(db)
    except Exception:
        logger.exception("Restart sweep failed; starting the workers anyway")
    tasks = [
        asyncio.create_task(orchestrator.run(), name="launch-orchestrator"),
        asyncio.create_task(sweep_loop(db, on_requeued=orchestrator.wake), name="launch-sweep"),
    ]
    if elevenlabs is not None:
        watcher = CallWatcher(db, elevenlabs, complete_call=_complete_call_placeholder)
        tasks.append(asyncio.create_task(watcher.run(), name="call-watcher"))
    app.state.workers = Workers(
        orchestrator=orchestrator, tasks=tasks, gemini=gemini, elevenlabs=elevenlabs
    )


async def stop_workers(app: FastAPI) -> None:
    """Cancel the worker tasks and wait for them to finish. A no-op when none are running."""
    workers: Workers | None = app.state.workers
    app.state.workers = None
    if workers is None:
        return
    for task in workers.tasks:
        task.cancel()
    await asyncio.gather(*workers.tasks, return_exceptions=True)


def wake_orchestrator(app: FastAPI) -> None:
    """Tell the orchestrator there is new work; a no-op when no workers run."""
    workers: Workers | None = getattr(app.state, "workers", None)
    if workers is not None:
        workers.orchestrator.wake()

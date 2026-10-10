"""The call watcher: polls placed calls and drives each to the end.

A call that rang out is failed here within seconds ("No answer.") so the card offers Retry
instead of showing "Calling..." forever. A call someone spoke on is handed to `complete_call`,
which the post-call webhook also reaches; the unique event keys make the two doors idempotent.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.adapters.db import Database
from app.adapters.elevenlabs import ConversationSnapshot, ElevenLabsPort
from app.modules.threads.repo import LiveCall, StaleThread, apply_event, live_calls
from app.schemas.negotiation import EventType

logger = logging.getLogger(__name__)

NO_ANSWER = "No answer."

CompleteCall = Callable[[str, ConversationSnapshot], Awaitable[object]]


class CallWatcher:
    def __init__(
        self,
        db: Database,
        elevenlabs: ElevenLabsPort,
        *,
        complete_call: CompleteCall,
        poll_seconds: float = 2.0,
    ) -> None:
        self._db = db
        self._elevenlabs = elevenlabs
        self._complete_call = complete_call
        self._poll_seconds = poll_seconds

    async def check_once(self, *, batch_id: UUID | None = None) -> None:
        """Look at every live call once. A failure on one call is logged and skipped."""
        async with self._db.acquire() as conn:
            live = await live_calls(conn, batch_id=batch_id)
        for call in live:
            try:
                await self._check(call)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Checking the call on thread %s (conversation %s) failed",
                    call.thread.id,
                    call.conversation_id,
                )

    async def run(self) -> None:
        """Check every `poll_seconds` until cancelled."""
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Checking live calls failed")
            await asyncio.sleep(self._poll_seconds)

    async def _check(self, call: LiveCall) -> None:
        snapshot = await self._elevenlabs.get_conversation(call.conversation_id)
        if snapshot.status in ("initiated", "processing"):
            return
        if snapshot.status == "in-progress":
            if call.status == "calling":
                await self._apply(
                    call,
                    type="call_started",
                    target="in_call",
                )
            return
        if snapshot.status not in ("done", "failed"):
            logger.warning("Unknown conversation status %r", snapshot.status)
            return
        if call.status == "calling" and not snapshot.user_spoke:
            await self._apply(
                call,
                type="failed",
                target="failed",
                payload={"reason": NO_ANSWER},
                last_error=NO_ANSWER,
            )
            return
        await self._complete_call(call.conversation_id, snapshot)

    async def _apply(
        self,
        call: LiveCall,
        *,
        type: EventType,
        target: str,
        payload: dict | None = None,
        last_error: str | None = None,
    ) -> None:
        try:
            async with self._db.acquire() as conn:
                await apply_event(
                    conn,
                    call.thread,
                    expected={"calling"},
                    target=target,
                    type=type,
                    actor="system",
                    payload=payload,
                    last_error=last_error,
                    external_id=call.conversation_id,
                )
        except StaleThread:
            logger.info("Thread %s moved before the watcher could update it", call.thread.id)

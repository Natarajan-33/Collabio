"""The brand's moves on its threads: counter, resolve a reviewed reply, decline or withdraw,
and decline the rest of a batch.

A `BoardActions` belongs to one brand; another brand's thread or batch is `ThreadNotFound` /
`BatchNotFound`. Every write follows one pattern, in one transaction: `assert_fresh` (locks the
thread, checks the caller saw the newest terms), the status must allow the action
(`brand_actions`), then the event and status change together (`apply_event_id`) and the
notification is queued next to it (`enqueue`).

The brief's budget ceiling is read here, for the counter check. It never enters an event, an
outbox payload or a response other than the brand's own counter-preview message.
"""

import logging
from collections.abc import Collection
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.core.delta import compute_delta
from app.core.guardrails import brand_counter_violation
from app.core.terms import brand_offer_terms, terms_from_input
from app.core.thread_state import brand_actions
from app.modules.board import repo
from app.modules.board.service import BatchNotFound, ThreadNotFound, thread_card
from app.modules.discovery.service import initials
from app.modules.notify import outbox
from app.modules.threads import repo as threads_repo
from app.schemas.board import (
    BrandCounterPreview,
    BrandCounterPreviewRequest,
    BrandCounterRequest,
    BrandDeclineRequest,
    CreatorChip,
    DeclineRestItem,
    DeclineRestPreview,
    DeclineRestResult,
    ResolveRequest,
    ThreadCard,
)
from app.schemas.negotiation import NegotiationTerms
from app.schemas.packages import PackageTerms

logger = logging.getLogger(__name__)

TermsChanged = threads_repo.TermsChanged  # the router maps it to 409 `terms_changed`
StaleThread = threads_repo.StaleThread  # ... and this one to 409 `stale_status`

# Statuses where closing the thread is withdrawing an offer the creator has not answered (or
# never got); in every other open status the brand is declining the creator's position.
WITHDRAWABLE = frozenset({"awaiting_reply", "no_response", "queued", "failed"})
# Threads whose offer never reached the creator: closing them records the event but sends no mail.
NEVER_CONTACTED = frozenset({"queued", "failed"})
# What "decline the rest" closes: every thread that is not finished and not mid-work.
OPEN_STATUSES = frozenset(
    {
        "awaiting_reply",
        "countered",
        "accepted",
        "needs_review",
        "no_response",
        "queued",
        "failed",
    }
)


class ActionNotAllowed(Exception):
    """The thread's status does not allow this action; `status` is what it is now."""

    def __init__(self, status: str) -> None:
        super().__init__(f"Not allowed while the thread is {status}")
        self.status = status


class AboveCeiling(Exception):
    """The counter is above the brand's ceiling; the message names it (brand-only copy)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _terms(value: dict[str, Any] | None) -> NegotiationTerms | None:
    return None if value is None else NegotiationTerms.model_validate(value)


def _item(row: dict[str, Any]) -> DeclineRestItem:
    return DeclineRestItem(
        thread_id=row["id"],
        creator=CreatorChip(
            id=row["creator_id"],
            name=row["creator_name"],
            handle=row["creator_handle"],
            initials=initials(row["creator_name"]),
        ),
        status=row["status"],
    )


class BoardActions:
    def __init__(self, db: Database, brand_id: UUID) -> None:
        self._db = db
        self._brand_id = brand_id

    async def _lock(
        self,
        conn: asyncpg.Connection,
        thread_id: UUID,
        actions: Collection[str],
        based_on_event_id: int | None,
        *,
        fresh: bool = True,
    ) -> tuple[dict[str, Any], threads_repo.ThreadRef]:
        """Inside the caller's transaction: check ownership, lock the thread, check the caller
        saw the newest terms (`TermsChanged`) and that one of `actions` is open in its status
        (`ActionNotAllowed`). Returns the thread's context as it is under the lock, and its ref.
        """
        if await repo.batch_of_thread(conn, self._brand_id, thread_id) is None:
            raise ThreadNotFound
        if fresh:
            status = await threads_repo.assert_fresh(conn, thread_id, based_on_event_id)
        else:
            status = await repo.lock_status(conn, thread_id)
        if not set(actions) & set(brand_actions(status)):
            raise ActionNotAllowed(status)
        ctx = await repo.thread_context(conn, self._brand_id, thread_id)
        ref = await threads_repo.load_ref(conn, thread_id)
        assert ctx is not None and ref is not None
        return ctx, ref

    @staticmethod
    async def _brand_offer(conn: asyncpg.Connection, ctx: dict[str, Any]) -> NegotiationTerms:
        """The brand's current offer on this thread (Ruling 2)."""
        return brand_offer_terms(
            ask_videos=ctx["deliverables_count"],
            ask_price_cents=ctx["ask_price_cents"],
            go_live_by=ctx["go_live_by"],
            format=ctx["deliverables_format"],
            counter=await threads_repo.latest_brand_counter(conn, ctx["id"]),
        )

    @staticmethod
    def _violation(ctx: dict[str, Any], terms: NegotiationTerms) -> str | None:
        assert terms.price_cents is not None and terms.videos is not None
        return brand_counter_violation(
            price_cents=terms.price_cents,
            videos=terms.videos,
            brief_videos=ctx["deliverables_count"],
            ceiling_cents=ctx["budget_ceiling_cents"],
        )

    async def counter_preview(
        self, thread_id: UUID, req: BrandCounterPreviewRequest, today: date | None = None
    ) -> BrandCounterPreview:
        """The counter as it would be recorded, its delta, and the ceiling message when it is
        above the ceiling; writes nothing."""
        async with self._db.acquire() as conn:
            ctx = await repo.thread_context(conn, self._brand_id, thread_id)
        if ctx is None:
            raise ThreadNotFound
        if "counter" not in brand_actions(ctx["status"]):
            raise ActionNotAllowed(ctx["status"])
        terms = terms_from_input(
            req.terms, stance="offer", source="in_app", format=ctx["deliverables_format"]
        )
        delta = compute_delta(
            ctx["package_id"],
            PackageTerms.model_validate(ctx["package"]),
            ask_videos=ctx["deliverables_count"],
            ask_price_cents=ctx["ask_price_cents"],
            go_live_by=ctx["go_live_by"],
            today=today or _utc_today(),
            latest=terms,
        )
        return BrandCounterPreview(
            terms=terms, delta=delta, ceiling_violation=self._violation(ctx, terms)
        )

    async def counter(
        self, thread_id: UUID, req: BrandCounterRequest, today: date | None = None
    ) -> ThreadCard:
        """Send the creator a counter-offer: the thread goes back to `awaiting_reply` with a
        fresh expiry, and the creator is told.

        Raises `ThreadNotFound`, `TermsChanged`, `ActionNotAllowed`, and `AboveCeiling`.
        """
        async with self._db.transaction() as conn:
            ctx, ref = await self._lock(conn, thread_id, ["counter"], req.based_on_event_id)
            terms = terms_from_input(
                req.terms, stance="offer", source="in_app", format=ctx["deliverables_format"]
            )
            violation = self._violation(ctx, terms)
            if violation is not None:
                raise AboveCeiling(violation)
            note = (req.note or "").strip() or None
            extra = {"note": note} if note else {}
            event_id = await threads_repo.apply_event_id(
                conn,
                ref,
                expected={ctx["status"]},
                target="awaiting_reply",
                type="brand_counter_sent",
                actor="brand",
                payload=extra,
                terms=terms,
                latest_terms=terms,
                latest_terms_source="brand",
            )
            assert event_id is not None
            await outbox.enqueue(
                conn,
                kind="creator_brand_countered",
                thread_id=thread_id,
                event_id=event_id,
                payload=extra,
            )
            return await thread_card(conn, self._brand_id, thread_id, today or _utc_today())

    async def resolve(
        self, thread_id: UUID, req: ResolveRequest, today: date | None = None
    ) -> ThreadCard:
        """Settle a reply that needed review, recording the creator's position as the brand
        confirmed it (Ruling 4): their counter (terms given), their acceptance of the brand's
        current offer, or their decline. Nobody is notified: the brand just did this.
        """
        async with self._db.transaction() as conn:
            ctx, ref = await self._lock(conn, thread_id, ["resolve"], req.based_on_event_id)
            payload = {"resolved_review": True}
            match req.outcome:
                case "counter":
                    assert req.terms is not None  # the schema guarantees it
                    terms = terms_from_input(
                        req.terms,
                        stance="counter",
                        source="in_app",
                        format=ctx["deliverables_format"],
                    )
                    kind, target = "counter_submitted", "countered"
                case "accept":
                    terms = (await self._brand_offer(conn, ctx)).model_copy(
                        update={"stance": "accept"}
                    )
                    kind, target = "accepted", "accepted"
                case _:
                    terms, kind, target = None, "declined", "declined"
            event_id = await threads_repo.apply_event_id(
                conn,
                ref,
                expected={ctx["status"]},
                target=target,
                type=kind,  # type: ignore[arg-type]
                actor="brand",
                payload=payload,
                terms=terms,
                latest_terms=terms,
                latest_terms_source="creator" if terms is not None else None,
            )
            assert event_id is not None
            return await thread_card(conn, self._brand_id, thread_id, today or _utc_today())

    async def decline(
        self, thread_id: UUID, req: BrandDeclineRequest, today: date | None = None
    ) -> ThreadCard:
        """Withdraw an offer the creator has not answered, or decline their position, and tell
        them politely. `req.reason` is the brand's own note and is not kept or sent."""
        async with self._db.transaction() as conn:
            ctx, ref = await self._lock(conn, thread_id, ["withdraw", "decline"], None, fresh=False)
            reason = "withdrawn" if ctx["status"] in WITHDRAWABLE else "declined_by_brand"
            await self._close(conn, ref, ctx["status"], reason)
            return await thread_card(conn, self._brand_id, thread_id, today or _utc_today())

    @staticmethod
    async def _close(
        conn: asyncpg.Connection, ref: threads_repo.ThreadRef, status: str, reason: str
    ) -> None:
        """`closed_lost` with its `reason` code, in the caller's transaction, and the creator's
        notification unless the offer never reached them (`queued` / `failed`)."""
        event_id = await threads_repo.apply_event_id(
            conn,
            ref,
            expected={status},
            target="closed_lost",
            type="closed_lost",
            actor="brand",
            payload={"reason": reason},
        )
        assert event_id is not None
        if status in NEVER_CONTACTED:
            return
        await outbox.enqueue(
            conn,
            kind="creator_closed",
            thread_id=ref.id,
            event_id=event_id,
            payload={"reason": reason},
        )

    async def decline_rest_preview(self, batch_id: UUID) -> DeclineRestPreview:
        """The threads "decline the rest" would close, and the ones it would leave alone."""
        async with self._db.acquire() as conn:
            if await repo.get_batch(conn, self._brand_id, batch_id) is None:
                raise BatchNotFound
            rows = await repo.batch_thread_statuses(conn, self._brand_id, batch_id)
        return DeclineRestPreview(
            will_close=[_item(r) for r in rows if r["status"] in OPEN_STATUSES],
            skipped=[_item(r) for r in rows if r["status"] not in OPEN_STATUSES],
        )

    async def _close_not_selected(self, thread_id: UUID) -> None:
        """Close one thread as `not_selected`, in its own transaction. Raises `StaleThread` when
        it is no longer in an open status."""
        async with self._db.transaction() as conn:
            status = await repo.lock_status(conn, thread_id)
            ref = await threads_repo.load_ref(conn, thread_id)
            if ref is None or status not in OPEN_STATUSES:
                raise StaleThread(f"Thread {thread_id} is {status}")
            await self._close(conn, ref, status, "not_selected")

    async def decline_rest(self, batch_id: UUID) -> DeclineRestResult:
        """Politely close every open thread of the batch, each in its own transaction: one that
        fails (or moved on meanwhile) is reported in `failed` and never stops the others."""
        async with self._db.acquire() as conn:
            if await repo.get_batch(conn, self._brand_id, batch_id) is None:
                raise BatchNotFound
            rows = await repo.batch_thread_statuses(conn, self._brand_id, batch_id)
        closed: list[UUID] = []
        failed: list[UUID] = []
        for row in rows:
            if row["status"] not in OPEN_STATUSES:
                continue
            try:
                await self._close_not_selected(row["id"])
            except Exception as exc:  # noqa: BLE001  (per-thread isolation: report it, go on)
                logger.warning(
                    "decline-rest failed for thread %s: %s", row["id"], type(exc).__name__
                )
                failed.append(row["id"])
            else:
                closed.append(row["id"])
        return DeclineRestResult(closed=closed, failed=failed)

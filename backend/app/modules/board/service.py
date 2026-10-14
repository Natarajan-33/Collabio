"""The comparison board: batches, their cards ranked by best value, thread detail and Retry.

A `BoardService` belongs to one brand; another brand's batch or thread is `BatchNotFound` /
`ThreadNotFound`, never a permission error. The brief's budget ceiling is loaded to feed
`rank_threads` and the brand-only `BriefSummary`; no creator email, phone or floor is read.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.core.delta import compute_delta
from app.core.ranking import RankInput, rank_threads
from app.core.thread_state import brand_actions
from app.modules.board import repo
from app.modules.discovery.service import initials, package_summary
from app.modules.threads import repo as threads_repo
from app.schemas.board import (
    BatchKpis,
    BatchListItem,
    BatchView,
    BestValue,
    BriefSummary,
    CreatorChip,
    EmailPreview,
    ThreadCard,
    ThreadDetail,
    ThreadEventView,
    TranscriptView,
)
from app.schemas.negotiation import TERMS_EVENT_TYPES, NegotiationTerms
from app.schemas.packages import PackageTerms

CONTACT_EVENTS = {"email_sent", "call_started"}
REPLY_EVENTS = set(repo.REPLY_EVENTS)


class BatchNotFound(Exception):
    """No such batch among this brand's batches."""


class ThreadNotFound(Exception):
    """No such thread among this brand's threads."""


class ThreadNotFailed(Exception):
    """Retry was asked for a thread that is not `failed`."""


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _terms(value: dict[str, Any] | None) -> NegotiationTerms | None:
    return None if value is None else NegotiationTerms.model_validate(value)


def _event_view(row: dict[str, Any]) -> ThreadEventView:
    return ThreadEventView(
        id=row["id"],
        type=row["type"],
        actor=row["actor"],
        created_at=row["created_at"],
        payload=row["payload"],
        terms=_terms(row["terms"]),
    )


def _email_preview(events: list[dict[str, Any]]) -> EmailPreview | None:
    """The newest draft, with `delivered` from the newest `email_sent` (None until sent)."""
    drafted = next((e for e in reversed(events) if e["type"] == "email_drafted"), None)
    if drafted is None:
        return None
    sent = next((e for e in reversed(events) if e["type"] == "email_sent"), None)
    return EmailPreview(
        subject=drafted["payload"].get("subject", ""),
        body_text=drafted["payload"].get("body_text", ""),
        delivered=None if sent is None else sent["payload"].get("delivered"),
    )


def _card(
    row: dict[str, Any],
    events: list[dict[str, Any]],
    best_value: BestValue,
    brief: dict[str, Any],
    today: date,
) -> ThreadCard:
    latest = _terms(row["latest_terms"])
    package = PackageTerms.model_validate(row["package"])
    delta = compute_delta(
        row["package_id"],
        package,
        ask_videos=brief["deliverables_count"],
        ask_price_cents=brief["ask_price_cents"],
        go_live_by=brief["go_live_by"],
        today=today,
        latest=latest,
    )
    return ThreadCard(
        id=row["id"],
        creator=CreatorChip(
            id=row["creator_id"],
            name=row["creator_name"],
            handle=row["creator_handle"],
            initials=initials(row["creator_name"]),
        ),
        channel_plan=row["channel_plan"],
        status=row["status"],
        package=package_summary(row["package_id"], package),
        latest_terms=latest,
        latest_terms_source=row["latest_terms_source"],
        delta=delta,
        last_event=_event_view(events[-1]) if events else None,
        email=_email_preview(events),
        live_offers=[
            _terms(e["terms"]) for e in events if e["type"] == "call_offer_logged" and e["terms"]
        ],
        best_value=best_value,
        last_error=row["last_error"],
        terms_event_id=next(
            (e["id"] for e in reversed(events) if e["type"] in TERMS_EVENT_TYPES), None
        ),
        deal_id=row["deal_id"],
        expires_at=row["expires_at"],
        allowed_actions=brand_actions(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _build_view(
    batch: dict[str, Any],
    threads: list[dict[str, Any]],
    events: list[dict[str, Any]],
    today: date,
) -> BatchView:
    by_thread: dict[UUID, list[dict[str, Any]]] = {}
    for event in events:
        by_thread.setdefault(event["thread_id"], []).append(event)

    values = rank_threads(
        [
            RankInput(
                thread_id=t["id"],
                status=t["status"],
                terms=_terms(t["latest_terms"]),
                terms_source=t["latest_terms_source"],
                engagement_rate=t["engagement_rate"],
                similarity=None if t["similarity"] is None else float(t["similarity"]),
            )
            for t in threads
        ],
        ceiling_cents=batch["budget_ceiling_cents"],
        brief_videos=batch["deliverables_count"],
        go_live_by=batch["go_live_by"],
    )
    cards = [_card(t, by_thread.get(t["id"], []), values[t["id"]], batch, today) for t in threads]

    def order(card: ThreadCard) -> tuple[int, int, datetime, str]:
        rank = card.best_value.rank if card.best_value else None
        if rank is None:
            return (1, 0, card.created_at, str(card.id))
        return (0, rank, card.created_at, str(card.id))

    cards.sort(key=order)

    def types(thread_id: UUID) -> set[str]:
        return {e["type"] for e in by_thread.get(thread_id, [])}

    per_video = [v.per_video_cents for v in values.values() if v.eligible and v.per_video_cents]
    kpis = BatchKpis(
        contacted=sum(1 for t in threads if CONTACT_EVENTS & types(t["id"])),
        replied=sum(1 for t in threads if REPLY_EVENTS & types(t["id"])),
        countered=sum(1 for t in threads if t["status"] == "countered"),
        hired=sum(1 for t in threads if t["status"] == "awarded"),
        best_per_video_cents=min(per_video) if per_video else None,
        launched_at=batch["launched_at"],
    )
    return BatchView(
        id=batch["id"],
        brief=BriefSummary(
            brief_id=batch["brief_id"],
            product_name=batch["product_name"],
            deliverables_count=batch["deliverables_count"],
            deliverables_format=batch["deliverables_format"],
            ask_price_cents=batch["ask_price_cents"],
            budget_ceiling_cents=batch["budget_ceiling_cents"],
            go_live_by=batch["go_live_by"],
            follow_up_policy=batch["follow_up_policy"],
            hires_target=batch["hires_target"],
        ),
        kpis=kpis,
        threads=cards,
    )


async def thread_card(
    conn: asyncpg.Connection, brand_id: UUID, thread_id: UUID, today: date
) -> ThreadCard:
    """The thread's card, ranked among its batch; `ThreadNotFound` for another brand's thread.

    Reads through `conn`, so inside a transaction it shows the caller's own uncommitted writes.
    """
    batch_id = await repo.batch_of_thread(conn, brand_id, thread_id)
    if batch_id is None:
        raise ThreadNotFound
    batch = await repo.get_batch(conn, brand_id, batch_id)
    assert batch is not None
    threads = await repo.batch_threads(conn, brand_id, batch_id)
    events = await repo.batch_events(conn, brand_id, batch_id)
    view = _build_view(batch, threads, events, today)
    return next(card for card in view.threads if card.id == thread_id)


class BoardService:
    def __init__(self, db: Database, brand_id: UUID) -> None:
        self._db = db
        self._brand_id = brand_id

    async def list_batches(self) -> list[BatchListItem]:
        """The brand's batches, newest first, with their headline counts."""
        async with self._db.acquire() as conn:
            rows = await repo.list_batches(conn, self._brand_id)
        return [BatchListItem(**row) for row in rows]

    async def batch_view(self, batch_id: UUID, today: date | None = None) -> BatchView:
        """The batch's cards ranked by best value, with the brief and the KPIs."""
        async with self._db.acquire() as conn:
            return await self._view(conn, batch_id, today or _utc_today())

    async def _view(self, conn: asyncpg.Connection, batch_id: UUID, today: date) -> BatchView:
        batch = await repo.get_batch(conn, self._brand_id, batch_id)
        if batch is None:
            raise BatchNotFound
        threads = await repo.batch_threads(conn, self._brand_id, batch_id)
        events = await repo.batch_events(conn, self._brand_id, batch_id)
        return _build_view(batch, threads, events, today)

    async def _card(self, conn: asyncpg.Connection, thread_id: UUID, today: date) -> ThreadCard:
        """The thread's card, ranked among its batch."""
        return await thread_card(conn, self._brand_id, thread_id, today)

    async def thread_detail(self, thread_id: UUID, today: date | None = None) -> ThreadDetail:
        """The thread's card with its whole event log (oldest first) and transcripts (newest
        first)."""
        async with self._db.acquire() as conn:
            card = await self._card(conn, thread_id, today or _utc_today())
            events = await repo.thread_events(conn, self._brand_id, thread_id)
            transcripts = await repo.thread_transcripts(conn, self._brand_id, thread_id)
        return ThreadDetail(
            card=card,
            events=[_event_view(e) for e in events],
            transcripts=[TranscriptView(**t) for t in transcripts],
        )

    async def retry(self, thread_id: UUID, today: date | None = None) -> ThreadCard:
        """Requeue a failed thread, in one transaction with its `retried` event.

        Raises `ThreadNotFound`, and `ThreadNotFailed` when the thread is in any other status
        (or someone else moved it first).
        """
        today = today or _utc_today()
        async with self._db.transaction() as conn:
            if await repo.batch_of_thread(conn, self._brand_id, thread_id) is None:
                raise ThreadNotFound
            ref = await threads_repo.load_ref(conn, thread_id)
            assert ref is not None
            try:
                await threads_repo.apply_event(
                    conn,
                    ref,
                    expected={"failed"},
                    target="queued",
                    type="retried",
                    actor="brand",
                )
            except threads_repo.StaleThread as exc:
                raise ThreadNotFailed from exc
            await repo.reset_for_retry(conn, thread_id)
            return await self._card(conn, thread_id, today)

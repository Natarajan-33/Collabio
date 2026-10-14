"""The creator's offers: list, counts and the offer desk.

An `OffersService` belongs to one creator; another creator's thread, or one that has not
reached the creator yet, is `OfferNotFound`, never a permission error. This is the one place
the creator's package floor is read, and only the owner's. The brief's budget ceiling and
contact email are never selected.
"""

from datetime import date
from typing import Any
from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.core.delta import compute_delta
from app.core.guardrails import floor_shortfall
from app.core.terms import (
    brand_offer_terms,
    ensure_go_live_not_past,
    terms_changed,
    terms_from_input,
)
from app.core.thread_state import CREATOR_VISIBLE, creator_actions, waiting_on
from app.modules.discovery.service import package_summary
from app.modules.notify import outbox
from app.modules.offers import repo
from app.modules.threads import repo as threads_repo
from app.schemas.board import ThreadEventView, TranscriptView
from app.schemas.negotiation import NegotiationTerms
from app.schemas.offers import (
    AcceptRequest,
    BrandChip,
    CreatorCounterPreview,
    CreatorCounterPreviewRequest,
    CreatorCounterRequest,
    DeclineRequest,
    OfferCounts,
    OfferDesk,
    OfferListItem,
    OfferSort,
    OfferTab,
    TermsColumn,
)
from app.schemas.packages import PackageTerms

# Which statuses each tab holds (Ruling 6); `follow_up_suggested` is in no tab.
TAB_STATUSES: dict[str, frozenset[str]] = {
    "needs_you": frozenset({"awaiting_reply", "no_response"}),
    "waiting": frozenset({"countered", "accepted", "needs_review"}),
    "booked": frozenset({"awarded"}),
    "closed": frozenset({"declined", "closed_lost"}),
}


class OfferNotFound(Exception):
    """No such offer among this creator's visible offers."""


class ActionNotAllowed(Exception):
    """The offer's status does not allow this action; `status` is what it is now."""

    def __init__(self, status: str) -> None:
        super().__init__(f"Not allowed while the offer is {status}")
        self.status = status


class BelowFloor(Exception):
    """The counter is under the creator's own floor and was not confirmed."""

    def __init__(self, by_cents: int) -> None:
        super().__init__(f"{by_cents} cents below the floor")
        self.by_cents = by_cents


TermsChanged = threads_repo.TermsChanged  # the router maps it to 409 `terms_changed`


async def find_creator_id(db: Database, profile_id: UUID) -> UUID | None:
    """The id of the signed-in user's creator, or None when onboarding never created one."""
    async with db.acquire() as conn:
        return await repo.creator_for_profile(conn, profile_id)


def sort_offers(items: list[OfferListItem], sort: OfferSort) -> list[OfferListItem]:
    """The offers in the order the creator asked for (Ruling 7); ties go newest first.

    `fit` puts the ask closest to the creator's listed price per video first, `revenue` the
    highest total value, `timeline` the soonest go-live date.
    """
    newest_first = sorted(items, key=lambda i: i.updated_at, reverse=True)  # stable base order
    if sort == "fit":
        return sorted(newest_first, key=lambda i: i.fit_gap)
    if sort == "revenue":
        return sorted(newest_first, key=lambda i: -i.total_value_cents)
    return sorted(newest_first, key=lambda i: i.go_live_by)


def _terms(value: dict[str, Any] | None) -> NegotiationTerms | None:
    return None if value is None else NegotiationTerms.model_validate(value)


def _column(terms: NegotiationTerms | None) -> TermsColumn | None:
    if terms is None:
        return None
    per_video = None
    if terms.videos and terms.price_cents:
        per_video = round(terms.price_cents / terms.videos)
    return TermsColumn(
        videos=terms.videos,
        price_cents=terms.price_cents,
        per_video_cents=per_video,
        go_live_by=terms.go_live_by,
        conditions=list(terms.conditions),
    )


def _brand_offer(row: dict[str, Any], *, with_counter: bool = True) -> NegotiationTerms:
    """The brand's current offer on this thread (Ruling 2), or its opening ask."""
    return brand_offer_terms(
        ask_videos=row["deliverables_count"],
        ask_price_cents=row["ask_price_cents"],
        go_live_by=row["go_live_by"],
        format=row["deliverables_format"],
        counter=_terms(row["brand_counter"]) if with_counter else None,
    )


def _creator_latest(row: dict[str, Any]) -> NegotiationTerms | None:
    """The creator's own latest position. Latest terms from the brand side (an agent's spoken
    offer on a call) are not the brand's offer (Ruling 2) and never show on the creator side."""
    if row["latest_terms_source"] != "creator":
        return None
    return _terms(row["latest_terms"])


def _delta(row: dict[str, Any], today: date, latest: NegotiationTerms | None):
    return compute_delta(
        row["package_id"],
        PackageTerms.model_validate(row["package"]),
        ask_videos=row["deliverables_count"],
        ask_price_cents=row["ask_price_cents"],
        go_live_by=row["go_live_by"],
        today=today,
        latest=latest,
    )


def _list_item(row: dict[str, Any], today: date) -> OfferListItem:
    package = PackageTerms.model_validate(row["package"])
    latest = _creator_latest(row)
    delta = _delta(row, today, latest)
    price = latest.price_cents if latest and latest.price_cents else None
    if price is None:
        price = _brand_offer(row).price_cents
    assert price is not None
    return OfferListItem(
        thread_id=row["id"],
        brand=BrandChip(id=row["brand_id"], name=row["brand_name"]),
        product_name=row["product_name"],
        status=row["status"],
        waiting_on=waiting_on(row["status"]),
        package=package_summary(row["package_id"], package),
        delta_headline=delta.headline,
        delta_flags=delta.flags,
        total_value_cents=price,
        go_live_by=row["go_live_by"],
        expires_at=row["expires_at"],
        updated_at=row["updated_at"],
        fit_gap=abs(delta.ask_per_video_cents - delta.listed_per_video_cents)
        / delta.listed_per_video_cents,
    )


def _changed(row: dict[str, Any], offer: NegotiationTerms, latest: NegotiationTerms | None):
    """What moved: the brand's counter against its opening ask, else my latest against their
    offer (a field I left open counts as agreeing)."""
    if row["brand_counter"] is not None:
        return terms_changed(_brand_offer(row, with_counter=False), offer)
    if latest is None:
        return []
    filled = latest.model_copy(
        update={
            "videos": latest.videos or offer.videos,
            "format": latest.format or offer.format,
            "go_live_by": latest.go_live_by or offer.go_live_by,
        }
    )
    return terms_changed(offer, filled)


async def build_desk(
    conn: asyncpg.Connection, creator_id: UUID, thread_id: UUID, today: date
) -> OfferDesk:
    """The offer desk of one of the creator's visible threads; `OfferNotFound` otherwise."""
    row = await repo.get_offer(conn, creator_id, thread_id, CREATOR_VISIBLE)
    if row is None:
        raise OfferNotFound
    package = PackageTerms.model_validate(row["package"])
    summary = package_summary(row["package_id"], package)
    offer = _brand_offer(row)
    latest = _creator_latest(row)
    events = await repo.offer_events(conn, creator_id, thread_id)
    transcripts = await repo.offer_transcripts(conn, creator_id, thread_id)
    return OfferDesk(
        thread_id=row["id"],
        brand=BrandChip(id=row["brand_id"], name=row["brand_name"]),
        product_name=row["product_name"],
        product_summary=row["product_summary"],
        status=row["status"],
        waiting_on=waiting_on(row["status"]),
        package=summary,
        delta=_delta(row, today, latest),
        my_package=TermsColumn(
            videos=package.volume_count,
            price_cents=package.base_price_cents,
            per_video_cents=summary.per_video_cents,
            go_live_by=None,
            conditions=[],
        ),
        their_ask=_column(offer),
        latest=_column(latest),
        latest_source="creator" if latest is not None else None,
        changed=_changed(row, offer, latest),
        brand_note=await repo.newest_brand_note(conn, creator_id, thread_id),
        terms_event_id=await threads_repo.latest_terms_event_id(conn, thread_id),
        allowed_actions=creator_actions(row["status"]),
        floor_price_cents=row["floor_price_cents"],
        events=[ThreadEventView(**e) for e in events],
        transcripts=[TranscriptView(**t) for t in transcripts],
        deal_id=row["deal_id"],
        expires_at=row["expires_at"],
    )


class OffersService:
    def __init__(self, db: Database, creator_id: UUID) -> None:
        self._db = db
        self._creator_id = creator_id

    async def counts(self) -> OfferCounts:
        """How many offers each tab holds."""
        async with self._db.acquire() as conn:
            by_status = await repo.status_counts(conn, self._creator_id, CREATOR_VISIBLE)
        totals = {tab: sum(by_status.get(s, 0) for s in sts) for tab, sts in TAB_STATUSES.items()}
        return OfferCounts(**totals)

    async def desk(self, thread_id: UUID, today: date) -> OfferDesk:
        async with self._db.acquire() as conn:
            return await build_desk(conn, self._creator_id, thread_id, today)

    async def _lock(
        self,
        conn: asyncpg.Connection,
        thread_id: UUID,
        action: str,
        based_on_event_id: int | None,
        *,
        fresh: bool = True,
    ) -> tuple[dict[str, Any], threads_repo.ThreadRef]:
        """Inside the caller's transaction: check ownership, lock the thread, check the caller
        saw the newest terms (`TermsChanged`) and that `action` is open in its status
        (`ActionNotAllowed`). Returns the offer row as it is under the lock, and the thread ref.
        """
        if await repo.get_offer(conn, self._creator_id, thread_id, CREATOR_VISIBLE) is None:
            raise OfferNotFound
        if fresh:
            status = await threads_repo.assert_fresh(conn, thread_id, based_on_event_id)
        else:
            status = await repo.lock_status(conn, thread_id)
        if action not in creator_actions(status):
            raise ActionNotAllowed(status)
        row = await repo.get_offer(conn, self._creator_id, thread_id, CREATOR_VISIBLE)
        ref = await threads_repo.load_ref(conn, thread_id)
        assert row is not None and ref is not None
        return row, ref

    @staticmethod
    def _shortfall(row: dict[str, Any], terms: NegotiationTerms) -> int | None:
        """How far the counter is below the creator's own floor, or None. Only this number
        leaves; the floor itself stays here."""
        floor = row["floor_price_cents"]
        if floor is None or terms.price_cents is None or terms.videos is None:
            return None
        return floor_shortfall(
            price_cents=terms.price_cents,
            videos=terms.videos,
            package_volume=row["package"]["volume_count"],
            floor_cents=floor,
        )

    async def counter_preview(
        self, thread_id: UUID, req: CreatorCounterPreviewRequest, today: date
    ) -> CreatorCounterPreview:
        """The counter as it would be recorded, with its delta and floor shortfall; writes
        nothing."""
        async with self._db.acquire() as conn:
            row = await repo.get_offer(conn, self._creator_id, thread_id, CREATOR_VISIBLE)
        if row is None:
            raise OfferNotFound
        if "counter" not in creator_actions(row["status"]):
            raise ActionNotAllowed(row["status"])
        terms = terms_from_input(
            req.terms, stance="counter", source="in_app", format=row["deliverables_format"]
        )
        return CreatorCounterPreview(
            terms=terms,
            delta=_delta(row, today, latest=terms),
            below_floor_by_cents=self._shortfall(row, terms),
        )

    async def counter(self, thread_id: UUID, req: CreatorCounterRequest, today: date) -> OfferDesk:
        """Record the creator's counter (or revision) and tell the brand.

        Raises `OfferNotFound`, `TermsChanged`, `ActionNotAllowed`, and `BelowFloor` when the
        price is under the floor and `confirm_below_floor` is not set.
        """
        async with self._db.transaction() as conn:
            row, ref = await self._lock(conn, thread_id, "counter", req.based_on_event_id)
            ensure_go_live_not_past(req.terms, today)
            terms = terms_from_input(
                req.terms, stance="counter", source="in_app", format=row["deliverables_format"]
            )
            shortfall = self._shortfall(row, terms)
            if shortfall is not None and not req.confirm_below_floor:
                raise BelowFloor(shortfall)
            note = (req.note or "").strip() or None
            extra = {"note": note} if note else {}
            event_id = await threads_repo.apply_event_id(
                conn,
                ref,
                expected={row["status"]},
                target="countered",
                type="counter_submitted",
                actor="creator",
                payload=extra,
                terms=terms,
                latest_terms=terms,
                latest_terms_source="creator",
            )
            assert event_id is not None
            await outbox.enqueue(
                conn,
                kind="brand_creator_countered",
                thread_id=thread_id,
                event_id=event_id,
                payload=extra,
            )
            return await build_desk(conn, self._creator_id, thread_id, today)

    async def accept(self, thread_id: UUID, req: AcceptRequest, today: date) -> OfferDesk:
        """Accept the brand's current offer (Ruling 3) and tell the brand."""
        async with self._db.transaction() as conn:
            row, ref = await self._lock(conn, thread_id, "accept", req.based_on_event_id)
            terms = _brand_offer(row).model_copy(update={"stance": "accept"})
            event_id = await threads_repo.apply_event_id(
                conn,
                ref,
                expected={row["status"]},
                target="accepted",
                type="accepted",
                actor="creator",
                terms=terms,
                latest_terms=terms,
                latest_terms_source="creator",
            )
            assert event_id is not None
            await outbox.enqueue(
                conn, kind="brand_creator_accepted", thread_id=thread_id, event_id=event_id
            )
            return await build_desk(conn, self._creator_id, thread_id, today)

    async def decline(self, thread_id: UUID, req: DeclineRequest, today: date) -> OfferDesk:
        """Decline the offer, with an optional reason the brand is told."""
        async with self._db.transaction() as conn:
            row, ref = await self._lock(conn, thread_id, "decline", None, fresh=False)
            reason = (req.reason or "").strip() or None
            extra = {"reason": reason} if reason else {}
            event_id = await threads_repo.apply_event_id(
                conn,
                ref,
                expected={row["status"]},
                target="declined",
                type="declined",
                actor="creator",
                payload=extra,
            )
            assert event_id is not None
            await outbox.enqueue(
                conn,
                kind="brand_creator_declined",
                thread_id=thread_id,
                event_id=event_id,
                payload=extra,
            )
            return await build_desk(conn, self._creator_id, thread_id, today)

    # Last on purpose: once defined, `list[...]` in a later annotation would name this method.
    async def list(self, tab: OfferTab | None, sort: OfferSort, today: date) -> list[OfferListItem]:
        """The creator's offers that have reached them, optionally one tab's, sorted."""
        statuses = CREATOR_VISIBLE if tab is None else TAB_STATUSES[tab]
        async with self._db.acquire() as conn:
            rows = await repo.list_offers(conn, self._creator_id, statuses)
        return sort_offers([_list_item(r, today) for r in rows], sort)

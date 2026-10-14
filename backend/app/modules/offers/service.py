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
from app.core.terms import brand_offer_terms, terms_changed
from app.core.thread_state import CREATOR_VISIBLE, creator_actions, waiting_on
from app.modules.discovery.service import package_summary
from app.modules.offers import repo
from app.modules.threads import repo as threads_repo
from app.schemas.board import ThreadEventView, TranscriptView
from app.schemas.negotiation import NegotiationTerms
from app.schemas.offers import (
    BrandChip,
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


def _delta(row: dict[str, Any], today: date):
    return compute_delta(
        row["package_id"],
        PackageTerms.model_validate(row["package"]),
        ask_videos=row["deliverables_count"],
        ask_price_cents=row["ask_price_cents"],
        go_live_by=row["go_live_by"],
        today=today,
        latest=_terms(row["latest_terms"]),
    )


def _list_item(row: dict[str, Any], today: date) -> OfferListItem:
    package = PackageTerms.model_validate(row["package"])
    delta = _delta(row, today)
    latest = _terms(row["latest_terms"])
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
    latest = _terms(row["latest_terms"]) if row["latest_terms_source"] == "creator" else None
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
        delta=_delta(row, today),
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

    # Last on purpose: once defined, `list[...]` in a later annotation would name this method.
    async def list(self, tab: OfferTab | None, sort: OfferSort, today: date) -> list[OfferListItem]:
        """The creator's offers that have reached them, optionally one tab's, sorted."""
        statuses = CREATOR_VISIBLE if tab is None else TAB_STATUSES[tab]
        async with self._db.acquire() as conn:
            rows = await repo.list_offers(conn, self._creator_id, statuses)
        return sort_offers([_list_item(r, today) for r in rows], sort)

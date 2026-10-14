"""Schemas for the creator's offers: the list, its counts and the offer desk.

The desk carries the creator's own package floor (`floor_price_cents`); nothing here carries
the brand's budget ceiling or contact email.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.thread_state import CreatorAction
from app.schemas.board import ThreadEventView, TranscriptView
from app.schemas.discovery import PackageSummary
from app.schemas.negotiation import (
    DeltaFlag,
    NegotiationTerms,
    PackageDelta,
    TermsInput,
    ThreadStatus,
)

WaitingOn = Literal["creator", "brand", "none"]
OfferTab = Literal["needs_you", "waiting", "booked", "closed"]
OfferSort = Literal["fit", "revenue", "timeline"]


class BrandChip(BaseModel):
    """Who an offer is from; never their contact details."""

    id: UUID
    name: str


class TermsColumn(BaseModel):
    """One column of the desk: a position as videos, price and conditions."""

    videos: int | None
    price_cents: int | None
    per_video_cents: int | None
    go_live_by: date | None
    conditions: list[str]


class OfferListItem(BaseModel):
    thread_id: UUID
    brand: BrandChip
    product_name: str
    status: ThreadStatus
    waiting_on: WaitingOn
    package: PackageSummary
    delta_headline: str
    delta_flags: list[DeltaFlag]
    total_value_cents: int
    go_live_by: date
    expires_at: datetime | None
    updated_at: datetime
    # How far the ask per video is from the package's listed per video, as a fraction.
    fit_gap: float


class OfferCounts(BaseModel):
    needs_you: int
    waiting: int
    booked: int
    closed: int


class OfferDesk(BaseModel):
    """One offer in full: three columns (my package, their ask, my latest), the log and the
    actions open to the creator."""

    thread_id: UUID
    brand: BrandChip
    product_name: str
    product_summary: str | None
    status: ThreadStatus
    waiting_on: WaitingOn
    package: PackageSummary
    delta: PackageDelta
    my_package: TermsColumn
    their_ask: TermsColumn
    latest: TermsColumn | None
    latest_source: Literal["brand", "creator"] | None
    changed: list[str]
    brand_note: str | None
    terms_event_id: int | None
    allowed_actions: list[CreatorAction]
    floor_price_cents: int | None
    events: list[ThreadEventView]
    transcripts: list[TranscriptView]
    deal_id: UUID | None
    expires_at: datetime | None


class CreatorCounterPreviewRequest(BaseModel):
    terms: TermsInput


class CreatorCounterPreview(BaseModel):
    """The counter as it would be recorded, against the package, and how far it sits below the
    creator's own floor (None when it does not)."""

    terms: NegotiationTerms
    delta: PackageDelta
    below_floor_by_cents: int | None


class CreatorCounterRequest(BaseModel):
    terms: TermsInput
    based_on_event_id: int | None
    confirm_below_floor: bool = False
    note: str | None = Field(None, max_length=1000)


class AcceptRequest(BaseModel):
    based_on_event_id: int | None


class DeclineRequest(BaseModel):
    reason: str | None = Field(None, max_length=1000)

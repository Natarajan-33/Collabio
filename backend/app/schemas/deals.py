"""Deal vocabulary: the terms a deal was struck on and the payment milestones that go with it."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.board import CreatorChip
from app.schemas.packages import ContentType


class AgreedTerms(BaseModel):
    """Complete terms of an awarded deal: every deal field is filled."""

    videos: int
    format: ContentType
    price_cents: int
    go_live_by: date
    conditions: list[str] = []
    addons: list[str] = []


class MilestoneDraft(BaseModel):
    """One payment milestone as proposed or edited, before it is stored."""

    seq: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=80)
    amount_cents: int
    due_date: date


class AwardPreview(BaseModel):
    """What awarding a thread would do: the agreed terms, the even milestone split, and the
    brand-only checks (`over_ceiling_cents`, the hire target) it needs confirmed."""

    agreed: AgreedTerms
    milestones: list[MilestoneDraft]
    over_ceiling_cents: int | None
    hired: int
    hires_target: int
    would_reach_target: bool
    over_target: bool
    open_others: list[CreatorChip]
    # The threads behind `open_others`, in the same order: what "decline the rest" is sent, so
    # it closes the conversations the brand saw and nobody who opened up afterwards.
    open_other_thread_ids: list[UUID] = []
    terms_event_id: int | None


class AwardRequest(BaseModel):
    milestones: list[MilestoneDraft]
    based_on_event_id: int | None = None
    confirm_over_ceiling: bool = False
    confirm_over_target: bool = False


# M4 adds funding, delivery and payment states.
DealStatus = Literal["booked", "funded", "completed"]
MilestoneStatus = Literal["pending", "funded", "submitted", "needs_changes", "verified", "paid"]


class MilestoneView(MilestoneDraft):
    id: UUID
    status: MilestoneStatus


class DealParty(BaseModel):
    """One side of a deal. `email` is the contact address revealed by the booking."""

    name: str
    email: str | None


class DealView(BaseModel):
    id: UUID
    thread_id: UUID
    batch_id: UUID
    status: DealStatus
    product_name: str
    terms: AgreedTerms
    milestones: list[MilestoneView]
    brand: DealParty
    creator: DealParty
    creator_handle: str
    created_at: datetime


class DealListItem(BaseModel):
    """A deal in a list; the counterpart is named but never reachable from here."""

    id: UUID
    thread_id: UUID
    counterpart_name: str
    product_name: str
    videos: int
    price_cents: int
    go_live_by: date
    status: DealStatus
    created_at: datetime

"""Schemas for the comparison board."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.briefs import ChannelPlan, FollowUpPolicy
from app.schemas.discovery import PackageSummary
from app.schemas.negotiation import (
    Actor,
    EventType,
    NegotiationTerms,
    PackageDelta,
    ThreadStatus,
    TranscriptTurn,
)
from app.schemas.packages import ContentType


class BestValue(BaseModel):
    """A thread's place in the best-value ranking, with the reasons that earned it."""

    thread_id: UUID
    eligible: bool
    rank: int | None
    score: float | None
    per_video_cents: int | None
    reasons: list[str]
    ineligible_reason: str | None


class CreatorChip(BaseModel):
    """Who a thread is with; never their contact details."""

    id: UUID
    name: str
    handle: str
    initials: str


class EmailPreview(BaseModel):
    """The outreach email as drafted; `delivered` is False for a test address, None until sent."""

    subject: str
    body_text: str
    delivered: bool | None


class ThreadEventView(BaseModel):
    id: int
    type: EventType
    actor: Actor
    created_at: datetime
    payload: dict[str, Any]
    terms: NegotiationTerms | None


class TranscriptView(BaseModel):
    id: UUID
    kind: str
    created_at: datetime
    subject: str | None
    body_text: str | None
    turns: list[TranscriptTurn]
    summary: str | None


class ThreadCard(BaseModel):
    """One creator's negotiation on the board."""

    id: UUID
    creator: CreatorChip
    channel_plan: ChannelPlan
    status: ThreadStatus
    package: PackageSummary
    latest_terms: NegotiationTerms | None
    latest_terms_source: Literal["brand", "creator"] | None
    delta: PackageDelta
    last_event: ThreadEventView | None
    email: EmailPreview | None
    live_offers: list[NegotiationTerms]
    best_value: BestValue | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class BriefSummary(BaseModel):
    """The brief behind a batch. `budget_ceiling_cents` is brand-only (the board is too)."""

    brief_id: UUID
    product_name: str
    deliverables_count: int
    deliverables_format: ContentType
    ask_price_cents: int
    budget_ceiling_cents: int
    go_live_by: date
    follow_up_policy: FollowUpPolicy


class BatchKpis(BaseModel):
    contacted: int
    replied: int
    countered: int
    best_per_video_cents: int | None
    launched_at: datetime


class BatchView(BaseModel):
    id: UUID
    brief: BriefSummary
    kpis: BatchKpis
    threads: list[ThreadCard]


class BatchListItem(BaseModel):
    id: UUID
    brief_id: UUID
    product_name: str
    launched_at: datetime
    thread_count: int
    contacted: int
    replied: int
    countered: int


class ThreadDetail(BaseModel):
    card: ThreadCard
    events: list[ThreadEventView]
    transcripts: list[TranscriptView]

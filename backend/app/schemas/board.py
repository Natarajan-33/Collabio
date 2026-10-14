"""Schemas for the comparison board."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.thread_state import BrandAction
from app.schemas.briefs import ChannelPlan, FollowUpPolicy
from app.schemas.discovery import PackageSummary
from app.schemas.negotiation import (
    Actor,
    EventType,
    NegotiationTerms,
    PackageDelta,
    TermsInput,
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
    terms_event_id: int | None  # the newest terms-bearing event: send it back as based_on_event_id
    deal_id: UUID | None
    expires_at: datetime | None
    allowed_actions: list[BrandAction]
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
    hires_target: int


class BatchKpis(BaseModel):
    contacted: int
    replied: int
    countered: int
    hired: int
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


class BrandCounterPreviewRequest(BaseModel):
    terms: TermsInput


class BrandCounterPreview(BaseModel):
    """A brand counter as it would be recorded. `ceiling_violation` names the brand's own
    ceiling, so it appears only in brand responses."""

    terms: NegotiationTerms
    delta: PackageDelta
    ceiling_violation: str | None


class BrandCounterRequest(BaseModel):
    terms: TermsInput
    note: str | None = Field(None, max_length=1000)
    based_on_event_id: int | None = None


class ResolveRequest(BaseModel):
    """How the brand settles a reply it had to review: record a counter (with the terms it read
    out of the reply), accept the brand's own current offer, or record a decline."""

    outcome: Literal["counter", "accept", "decline"]
    terms: TermsInput | None = None
    based_on_event_id: int | None = None

    @model_validator(mode="after")
    def _counter_needs_terms(self) -> "ResolveRequest":
        if self.outcome == "counter" and self.terms is None:
            raise ValueError("A counter needs terms")
        return self


class BrandDeclineRequest(BaseModel):
    """`reason` is the brand's own note; it is accepted but never stored or sent on."""

    reason: str | None = Field(None, max_length=1000)


class DeclineRestItem(BaseModel):
    thread_id: UUID
    creator: CreatorChip
    status: ThreadStatus


class DeclineRestPreview(BaseModel):
    will_close: list[DeclineRestItem]
    skipped: list[DeclineRestItem]


class DeclineRestResult(BaseModel):
    closed: list[UUID]
    failed: list[UUID]

"""Negotiation vocabulary: the terms on the table, thread events, and the package delta."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.packages import ContentType

Stance = Literal["offer", "counter", "accept", "decline", "question", "no_commitment"]
TermsChannel = Literal["call", "email", "in_app"]
EventType = Literal[
    "queued",
    "email_drafted",
    "email_sent",
    "email_bounced",
    "call_placed",
    "call_started",
    "call_offer_logged",
    "call_ended",
    "email_received",
    "counter_submitted",
    "brand_counter_sent",
    "accepted",
    "declined",
    "follow_up_suggested",
    "follow_up_approved",
    "awarded",
    "closed_lost",
    "needs_review",
    "failed",
    "retried",
]
Actor = Literal["brand", "brand_agent", "creator", "system"]
DeltaFlag = Literal["below_base_price", "lead_time_conflict", "estimated"]


class NegotiationTerms(BaseModel):
    """Terms as stated by one side in one message or call; every deal field is optional."""

    videos: int | None = Field(None, ge=1)
    format: ContentType | None = None
    price_cents: int | None = Field(None, gt=0)
    go_live_by: date | None = None
    conditions: list[str] = []
    addons: list[str] = []
    stance: Stance
    source: TermsChannel
    confidence: float = Field(ge=0, le=1)
    open_questions: list[str] = []


class ListedPrice(BaseModel):
    """What the package lists for a number of videos; `estimated` when it was extrapolated."""

    cents: int
    estimated: bool


class PackageDelta(BaseModel):
    """How the brief's ask (and the creator's latest terms) differ from the listed package.

    `listed_price_cents` is the listed price for the ask's video count, not the base price.
    """

    package_id: UUID
    package_name: str
    listed_videos: int
    ask_videos: int
    latest_videos: int | None
    listed_price_cents: int
    ask_price_cents: int
    latest_price_cents: int | None
    listed_per_video_cents: int
    ask_per_video_cents: int
    latest_per_video_cents: int | None
    lead_time_days: int | None
    days_to_go_live: int
    headline: str
    latest_headline: str | None
    flags: list[DeltaFlag]


class TranscriptTurn(BaseModel):
    """One spoken turn of a call: who spoke, what they said, and seconds from the start."""

    role: Literal["agent", "user"]
    text: str
    t: float

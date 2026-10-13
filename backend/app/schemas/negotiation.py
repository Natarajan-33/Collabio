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
    "offer_expired",
]
# The statuses the `threads.status` check constraint allows; M2 uses the first ten.
ThreadStatus = Literal[
    "queued",
    "drafting",
    "awaiting_reply",
    "calling",
    "in_call",
    "countered",
    "accepted",
    "declined",
    "needs_review",
    "failed",
    "awarded",
    "closed_lost",
    "no_response",
    "follow_up_suggested",
]
Actor = Literal["brand", "brand_agent", "creator", "system"]
DeltaFlag = Literal["below_base_price", "lead_time_conflict", "estimated"]


class NegotiationTerms(BaseModel):
    """Terms as stated by one side in one message or call; every deal field is optional."""

    videos: int | None = Field(None, ge=1)
    format: ContentType | None = None
    # ge=1, not gt=0: exclusiveMinimum makes google-genai response_schema validation fail.
    price_cents: int | None = Field(None, ge=1)
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


class CheckCounterRequest(BaseModel):
    """The agent asks whether the creator's price fits. Agents speak dollars (Ruling 9)."""

    thread_id: UUID
    price_usd: float = Field(gt=0)
    videos: int = Field(ge=1)
    conditions: str = ""


class CheckCounterResponse(BaseModel):
    verdict: Literal["within", "over"]
    suggested_counter_price_usd: int | None
    talking_point: str


class LogOfferRequest(BaseModel):
    """The agent logs what was just said on the call, by either side."""

    thread_id: UUID
    price_usd: float | None = Field(None, gt=0)
    videos: int | None = Field(None, ge=1)
    go_live_by: str = ""
    conditions: str = ""
    stance: Stance
    speaker: Literal["creator", "agent"]


class LogOfferResponse(BaseModel):
    logged: bool

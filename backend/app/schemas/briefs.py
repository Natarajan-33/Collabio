"""Brief vocabulary and the field model a brand fills in (by voice or form) before launching."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.discovery import PackageSummary
from app.schemas.negotiation import PackageDelta
from app.schemas.packages import ContentType, RuleViolation

Flexibility = Literal["timeline", "price", "deliverables", "none"]
ChannelPlan = Literal["email", "call", "email_then_call"]
FollowUpPolicy = Literal["off", "suggest", "auto"]
BriefStatus = Literal["draft", "ready", "launched"]

# Fields a brief needs before it can launch, in the order the brief agent asks for them.
REQUIRED_BRIEF_FIELDS: tuple[str, ...] = (
    "brand_name",
    "product_name",
    "product_summary",
    "deliverables_count",
    "deliverables_format",
    "go_live_by",
    "budget_ceiling_cents",
    "ask_price_cents",
    "negotiation_ask",
    "flexibility",
    "contact_email",
)


class BriefFields(BaseModel):
    """The brief as captured so far; every field is optional until launch."""

    brand_name: str | None = None
    product_name: str | None = None
    product_summary: str | None = None
    deliverables_count: int | None = None
    deliverables_format: ContentType | None = None
    deliverable_length_s: int | None = None
    go_live_by: date | None = None
    budget_ceiling_cents: int | None = None
    ask_price_cents: int | None = None
    negotiation_ask: str | None = None
    flexibility: list[Flexibility] = []
    flexibility_note: str | None = None
    contact_email: str | None = None


INT4_MAX = 2**31 - 1


class CreateBriefRequest(BaseModel):
    """The creators a new brief is for, in the order the brand picked them."""

    creator_ids: list[UUID] = Field(min_length=1, max_length=10)


class BriefPatch(BriefFields):
    """Changes to a brief. Only the fields the client sent are applied; an explicit `null`
    clears a field (`flexibility: null` empties the list)."""

    flexibility: list[Flexibility] | None = None
    intake_conversation_id: str | None = None

    @field_validator(
        "deliverables_count", "deliverable_length_s", "budget_ceiling_cents", "ask_price_cents"
    )
    @classmethod
    def _fits_column(cls, value: int | None) -> int | None:
        """The columns are 32-bit; a larger number must be a 422, not a database error."""
        if value is not None and value > INT4_MAX:
            raise ValueError("number too large")
        return value


class DealBrief(BriefFields):
    """A brief as the brand sees it. `missing` and `violations` are computed on every read."""

    id: UUID
    status: BriefStatus
    creator_ids: list[UUID]
    approved_at: datetime | None
    batch_id: UUID | None
    missing: list[str]
    violations: list[RuleViolation]


class BriefCreatorPreview(BaseModel):
    """One creator of a brief: the package it is compared against and how to reach them."""

    creator_id: UUID
    name: str
    handle: str
    initials: str
    package: PackageSummary
    delta: PackageDelta | None
    default_channel: ChannelPlan
    call_allowed: bool
    excluded_reason: str | None


class BriefPreview(BaseModel):
    creators: list[BriefCreatorPreview]


class LaunchRequest(BaseModel):
    """How to launch: the channel per creator (a missing creator gets the default for their
    package and contact details) and what to do with creators who never reply."""

    channels: dict[UUID, ChannelPlan] = {}
    follow_up_policy: FollowUpPolicy = "off"


class LaunchExclusion(BaseModel):
    """A creator the launch left out, and why."""

    creator_id: UUID
    reason: str


class LaunchResponse(BaseModel):
    batch_id: UUID
    thread_count: int
    excluded: list[LaunchExclusion]


class VoiceSessionResponse(BaseModel):
    """What the browser needs to start a conversation with the brief agent."""

    conversation_token: str
    dynamic_variables: dict[str, str]

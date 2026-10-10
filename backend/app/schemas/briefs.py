"""Brief vocabulary and the field model a brand fills in (by voice or form) before launching."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas.packages import ContentType

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

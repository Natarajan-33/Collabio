"""Deal vocabulary: the terms a deal was struck on and the payment milestones that go with it."""

from datetime import date

from pydantic import BaseModel, Field

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

"""Schemas for the comparison board."""

from uuid import UUID

from pydantic import BaseModel


class BestValue(BaseModel):
    """A thread's place in the best-value ranking, with the reasons that earned it."""

    thread_id: UUID
    eligible: bool
    rank: int | None
    score: float | None
    per_video_cents: int | None
    reasons: list[str]
    ineligible_reason: str | None

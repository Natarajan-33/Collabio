"""Brand-facing creator discovery: search request and the creator cards it returns.

Cards carry only public marketplace data. Contact details, creators' private floor
prices and the search embedding never appear in these models.
"""

from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
)

from app.schemas.packages import (
    Addon,
    ContentType,
    Niche,
    PreferredChannel,
    VolumeBasis,
)


def _blank_to_none(value: Any) -> Any:
    """`"  "` -> `None`, other strings are stripped: a blank box means "no filter"."""
    if isinstance(value, str):
        return value.strip() or None
    return value


OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]
# Bounds what one search can send to the embedding model.
SearchText = Annotated[
    Annotated[str, StringConstraints(max_length=500)] | None, BeforeValidator(_blank_to_none)
]


class SearchFilters(BaseModel):
    """Hard filters; an empty list or a missing value leaves that dimension open.

    `max_price_cents` and `content_types` must hold on the same published package;
    `niches` matches creators with any of the listed niches.
    """

    niches: list[Niche] = []
    content_types: list[ContentType] = []
    max_price_cents: PositiveInt | None = None
    min_followers: NonNegativeInt | None = None
    region: OptionalText = None


class SearchRequest(BaseModel):
    """`query` is free text that ranks the filtered creators by meaning; without it the
    most-followed creators come first."""

    query: SearchText = None
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(24, ge=1, le=48)


class PackageSummary(BaseModel):
    """A published package as shown on a creator card. `one_liner` is its card text."""

    id: UUID
    name: str
    content_type: ContentType
    niche: Niche
    volume_count: int
    volume_basis: VolumeBasis
    base_price_cents: int
    per_video_cents: int
    one_liner: str
    lead_time_days: int | None
    preferred_channel: PreferredChannel
    addons: list[Addon]


class CreatorCard(BaseModel):
    """A creator with their published packages, cheapest first.

    `engagement_rate` is in percentage points (5.8 means 5.8%).
    """

    id: UUID
    handle: str
    name: str
    initials: str
    niches: list[str]
    region: str | None
    followers: int
    engagement_rate: float | None
    packages: list[PackageSummary]


class SearchResponse(BaseModel):
    """The request as applied (blank query and region normalised) and the matches in rank order."""

    query: str | None
    filters: SearchFilters
    results: list[CreatorCard]

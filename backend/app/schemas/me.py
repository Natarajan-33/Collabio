"""The signed-in user's account (`GET /me`) and role onboarding (`POST /onboarding`)."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, StringConstraints

from app.schemas.packages import Niche

Role = Literal["brand", "creator"]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# The same limit as a brief's product_summary (spec §7.3).
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def _normalize_handle(value: Any) -> Any:
    """`"@PriyaReviews "` -> `"priyareviews"`: handles are unique and case-insensitive."""
    return value.strip().removeprefix("@").lower() if isinstance(value, str) else value


Handle = Annotated[
    str, BeforeValidator(_normalize_handle), StringConstraints(pattern=r"^[a-z0-9._-]{2,30}$")
]
Niches = Annotated[
    list[Niche], Field(min_length=1), AfterValidator(lambda niches: list(dict.fromkeys(niches)))
]


class BrandOnboarding(BaseModel):
    """Onboarding as a brand ("I sell products"): the brand and the product it promotes."""

    role: Literal["brand"]
    display_name: Name
    company_name: Name
    category: Niche
    product_name: Name
    product_summary: Summary


class CreatorOnboarding(BaseModel):
    """Onboarding as a creator ("I create content"): the public creator profile."""

    role: Literal["creator"]
    display_name: Name
    handle: Handle
    niches: Niches
    region: Name


OnboardingRequest = Annotated[BrandOnboarding | CreatorOnboarding, Field(discriminator="role")]


class BrandSummary(BaseModel):
    id: UUID
    company_name: str
    category: str | None


class CreatorSummary(BaseModel):
    id: UUID
    handle: str
    name: str
    niches: list[str]
    region: str | None


class MeResponse(BaseModel):
    """The signed-in user; `role` is null until onboarding."""

    user_id: UUID
    email: str | None
    role: Role | None
    display_name: str | None
    brand: BrandSummary | None
    creator: CreatorSummary | None

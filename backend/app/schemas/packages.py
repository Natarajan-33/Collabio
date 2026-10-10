"""Creator packages: the published terms and the partial draft voice builds up."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, PositiveInt, StringConstraints

Niche = Literal["consumer_tech", "beauty", "fitness", "food", "gaming", "b2b_saas"]
ContentType = Literal["short_video", "long_video", "story", "live"]
VolumeBasis = Literal["per_week", "per_contract"]
PreferredChannel = Literal["email_first", "phone_ok", "email_only"]
# Where a creator is based, as stored on `creators.region` and matched by discovery.
Region = Literal["US", "IN", "UK", "CA", "AU"]
Currency = Literal["USD"]
PackageStatus = Literal["draft", "published"]


class Addon(BaseModel):
    """A priced add-on. `unit="video"` means one more video at this price."""

    name: str
    price_cents: int
    unit: Literal["video", "item"]


class Extra(BaseModel):
    """A priced extra that is not a deliverable (raw footage, a thumbnail pack)."""

    name: str
    price_cents: int


class PackageTerms(BaseModel):
    """A package's commercial terms: every `packages` column except ids, status, timestamps."""

    name: str
    content_type: ContentType
    niche: Niche
    volume_count: int
    volume_basis: VolumeBasis
    base_price_cents: int
    currency: Currency = "USD"
    included: list[str] = []
    freebies: list[str] = []
    addons: list[Addon] = []
    extras: list[Extra] = []
    slots_per_month: int | None = None
    lead_time_days: int | None = None
    preferred_channel: PreferredChannel


class PackageDraft(BaseModel):
    """`PackageTerms` with every field optional, as filled in by speech and clicks."""

    name: str | None = None
    content_type: ContentType | None = None
    niche: Niche | None = None
    volume_count: int | None = None
    volume_basis: VolumeBasis | None = None
    base_price_cents: int | None = None
    currency: Currency | None = None
    included: list[str] = []
    freebies: list[str] = []
    addons: list[Addon] = []
    extras: list[Extra] = []
    slots_per_month: int | None = None
    lead_time_days: int | None = None
    preferred_channel: PreferredChannel | None = None


class RuleViolation(BaseModel):
    """A package rule that fails, reported against the field the creator must change."""

    field: str
    message: str


class DraftFromSpeechRequest(BaseModel):
    """What the creator just said about a package, and the draft it is to be folded into."""

    transcript: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    current: PackageDraft = Field(default_factory=PackageDraft)


class ExtractedDraft(BaseModel):
    """What the model returns for a dictated package: the cleaned-up words (`heard`) and
    only the fields said in them. The service merges `draft` into the open draft."""

    heard: str
    draft: PackageDraft


class DraftResult(BaseModel):
    """The open draft after the latest dictation, what it still needs, and what it breaks.

    `missing` lists the required fields with no value yet, in the order the editor asks
    for them. `violations` are the publishing rules already broken by the values present.
    """

    draft: PackageDraft
    missing: list[str]
    violations: list[RuleViolation]
    heard: str


class FloorRequest(BaseModel):
    """The lowest price (cents) the creator will accept for a package; never shown to brands."""

    floor_price_cents: PositiveInt

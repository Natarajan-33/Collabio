"""A creator's own packages as the editor shows them: published or not, with the private floor.

Kept apart from `schemas.packages` because `MyPackage` extends the brand-facing
`PackageSummary`, which itself builds on `schemas.packages`.
"""

from pydantic import Field

from app.schemas.discovery import PackageSummary
from app.schemas.packages import Currency, Extra, PackageStatus


class MyPackage(PackageSummary):
    """A package card plus what only its creator sees or edits: status, private floor and
    the terms a card leaves out (`included`, `freebies`, `extras`, `slots_per_month`)."""

    status: PackageStatus
    floor_price_cents: int | None
    currency: Currency
    included: list[str]
    freebies: list[str]
    extras: list[Extra]
    slots_per_month: int | None


class SavedPackage(MyPackage):
    """A package after an edit that may touch the search index. `warnings` lists side
    effects that did not complete; the package itself was saved."""

    warnings: list[str] = Field(default_factory=list)

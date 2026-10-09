"""Package rules: what a draft still needs, how speech merges in, and what blocks publishing."""

from app.core.package_text import display_label
from app.schemas.packages import Addon, Extra, PackageDraft, PackageTerms, RuleViolation

# Fields a draft needs before it can be saved, in the order the editor asks for them.
REQUIRED_FIELDS = (
    "name",
    "content_type",
    "niche",
    "volume_count",
    "volume_basis",
    "base_price_cents",
    "preferred_channel",
)


def _item_key(item: str | Addon | Extra) -> str:
    """List items match by case-insensitive name (or text, for plain strings)."""
    return (item if isinstance(item, str) else item.name).strip().casefold()


def validate_package(pkg: PackageTerms, creator_niches: list[str]) -> list[RuleViolation]:
    """Every rule the package breaks, in field order; empty means it can be published."""
    violations: list[RuleViolation] = []

    def fail(field: str, message: str) -> None:
        violations.append(RuleViolation(field=field, message=message))

    if not pkg.name.strip():
        fail("name", "Give the package a name.")
    if pkg.niche not in creator_niches:
        yours = ", ".join(display_label(niche) for niche in creator_niches) or "none set"
        fail("niche", f"Pick one of your niches ({yours}).")
    if pkg.volume_count < 1:
        fail("volume_count", "Include at least 1 video.")
    if pkg.base_price_cents <= 0:
        fail("base_price_cents", "Set a base price above $0.")
    for field, items in (("addons", pkg.addons), ("extras", pkg.extras)):
        noun = "add-on" if field == "addons" else "extra"
        if len({_item_key(item) for item in items}) < len(items):
            fail(field, f"Each {noun} needs a different name.")
        if any(item.price_cents <= 0 for item in items):
            fail(field, f"Every {noun} needs a price above $0.")
    if pkg.slots_per_month is not None and pkg.slots_per_month < 0:
        fail("slots_per_month", "Slots per month can't be negative.")
    if pkg.lead_time_days is not None and pkg.lead_time_days < 0:
        fail("lead_time_days", "Lead time can't be negative.")
    return violations


def missing_fields(draft: PackageDraft) -> list[str]:
    """Required fields the draft has no value for (a blank name counts as missing)."""
    return [field for field in REQUIRED_FIELDS if _is_blank(getattr(draft, field))]


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _merge_items[T: (str, Addon, Extra)](current: list[T], extracted: list[T]) -> list[T]:
    """Extracted items replace same-named current items in place; new names are appended."""
    merged = {_item_key(item): item for item in current}
    for item in extracted:
        merged[_item_key(item)] = item
    return list(merged.values())


def merge_package_draft(current: PackageDraft, extracted: PackageDraft) -> PackageDraft:
    """Fold what was just said into the draft.

    Non-null extracted scalars overwrite; null ones keep the current value. List fields
    (add-ons, extras, included, freebies) merge by case-insensitive name, extracted winning.
    """
    merged = {}
    for field in PackageDraft.model_fields:
        cur, ext = getattr(current, field), getattr(extracted, field)
        if isinstance(cur, list):
            merged[field] = _merge_items(cur, ext)
        else:
            merged[field] = cur if ext is None else ext
    return PackageDraft(**merged)

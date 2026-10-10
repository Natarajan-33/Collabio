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


# Stand-ins for required fields the draft has no value for yet; `draft_violations` drops
# whatever they would trigger.
_NEUTRAL_VALUES = {
    "name": "Draft",
    "content_type": "short_video",
    "niche": "consumer_tech",
    "volume_count": 1,
    "volume_basis": "per_contract",
    "base_price_cents": 1,
    "preferred_channel": "email_first",
}


def terms_from_draft(draft: PackageDraft) -> PackageTerms:
    """The draft as package terms; unset optional fields take the terms' defaults.

    Raises pydantic's ValidationError when a required field is missing, so check
    `missing_fields` first.
    """
    return PackageTerms(**draft.model_dump(exclude_none=True))


def draft_violations(draft: PackageDraft, creator_niches: list[str]) -> list[RuleViolation]:
    """`validate_package` for a draft that may be incomplete: the rules broken by the
    values it already has. Fields it still lacks are `missing_fields`, not violations."""
    missing = set(missing_fields(draft))
    values = draft.model_dump(exclude_none=True) | {name: _NEUTRAL_VALUES[name] for name in missing}
    violations = validate_package(PackageTerms(**values), creator_niches)
    return [violation for violation in violations if violation.field not in missing]


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


def patch_package_draft(saved: PackageDraft, patch: PackageDraft) -> PackageDraft:
    """Apply an edit from the clicks editor: only the fields `patch` was given change.

    Unlike `merge_package_draft` (speech), a list in the patch replaces the saved list, so
    an item can be removed, and an explicit null clears an optional field.
    """
    values = saved.model_dump() | patch.model_dump(include=patch.model_fields_set)
    return PackageDraft(**values)

"""Brief rules: what a field may hold, what a brief still needs, and when it can launch."""

import re
from datetime import date

from app.schemas.briefs import REQUIRED_BRIEF_FIELDS, BriefFields
from app.schemas.packages import RuleViolation

BRIEF_FIELD_LABELS: dict[str, str] = {
    "brand_name": "brand name",
    "product_name": "product name",
    "product_summary": "product summary",
    "deliverables_count": "number of deliverables",
    "deliverables_format": "deliverable format",
    "deliverable_length_s": "video length",
    "go_live_by": "go-live date",
    "budget_ceiling_cents": "budget ceiling",
    "ask_price_cents": "opening ask",
    "negotiation_ask": "what to negotiate for",
    "flexibility": "flexibility",
    "flexibility_note": "flexibility note",
    "contact_email": "contact email",
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SUMMARY_MAX = 200


def field_error(field: str, value: object, today: date) -> str | None:
    """Why one value is not allowed for `field`, or None. Clearing a field (None) is always allowed."""
    if value is None:
        return None
    match field:
        case "product_summary" if isinstance(value, str) and len(value) > _SUMMARY_MAX:
            return f"Keep the product summary to {_SUMMARY_MAX} characters."
        case "deliverables_count" if isinstance(value, int) and value < 1:
            return "Ask for at least one deliverable."
        case "deliverable_length_s" if isinstance(value, int) and value <= 0:
            return "The video length must be more than 0 seconds."
        case "go_live_by" if isinstance(value, date) and value <= today:
            return "The go-live date must be in the future."
        case "budget_ceiling_cents" if isinstance(value, int) and value <= 0:
            return "The budget ceiling must be more than $0."
        case "ask_price_cents" if isinstance(value, int) and value <= 0:
            return "The opening ask must be more than $0."
        case "flexibility" if isinstance(value, list) and "none" in value and len(value) > 1:
            return "“None” can't be combined with other flexibility."
        case "contact_email" if isinstance(value, str) and not _EMAIL.match(value):
            return "Enter a valid contact email."
    return None


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, list) and not value


def missing_fields(brief: BriefFields) -> list[str]:
    """Required fields still empty, in `REQUIRED_BRIEF_FIELDS` order."""
    return [f for f in REQUIRED_BRIEF_FIELDS if _is_blank(getattr(brief, f))]


def violations(brief: BriefFields, today: date) -> list[RuleViolation]:
    """Every rule the filled-in fields break, plus the ask-versus-ceiling rule."""
    found: list[RuleViolation] = []
    for field in BriefFields.model_fields:
        value = getattr(brief, field)
        if _is_blank(value):
            continue
        message = field_error(field, value, today)
        if message:
            found.append(RuleViolation(field=field, message=message))
    ask, ceiling = brief.ask_price_cents, brief.budget_ceiling_cents
    if ask is not None and ceiling is not None and ask > ceiling:
        found.append(
            RuleViolation(
                field="ask_price_cents",
                message="The opening ask can't be above the budget ceiling.",
            )
        )
    return found


def is_launchable(brief: BriefFields, today: date) -> bool:
    """True when nothing required is missing and no rule is broken."""
    return not missing_fields(brief) and not violations(brief, today)

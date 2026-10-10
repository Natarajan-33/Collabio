"""The brief agent's dynamic variables: what it knows about the brief when a voice session starts.

`current_brief_json` carries the brand's own private budget ceiling. That is deliberate: this
agent talks only to the brand, never to a creator.
"""

import json
from collections.abc import Sequence
from datetime import date

from app.core import brief_rules
from app.schemas.briefs import BriefFields, DealBrief


def brief_dynamic_variables(
    brief: DealBrief, creators: Sequence[tuple[str, str]], today: date
) -> dict[str, str]:
    """The variables the brief agent's prompt uses. `creators` are pairs of a creator's name
    and the one-liner of the package the brief is compared against."""
    fields = BriefFields(**{name: getattr(brief, name) for name in BriefFields.model_fields})
    missing = [brief_rules.BRIEF_FIELD_LABELS[f] for f in brief_rules.missing_fields(fields)]
    return {
        "brief_id": str(brief.id),
        "brand_name": brief.brand_name or "",
        "product_name": brief.product_name or "",
        "product_summary": brief.product_summary or "",
        "contact_email": brief.contact_email or "",
        "selected_creators_summary": "; ".join(f"{name} — {line}" for name, line in creators),
        "current_brief_json": json.dumps(fields.model_dump(mode="json", exclude_none=True)),
        "missing_fields": ", ".join(missing) or "nothing",
        "today": today.isoformat(),
    }

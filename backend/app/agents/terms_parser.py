"""Turns a brand's plain-English performance bonus into validated `BonusTerms`.

Claude (Haiku) answers with structured JSON in dollars and view counts; the engine owns the
conversion to cents and the validation. When the text is ambiguous the model asks instead.
"""

import json
from decimal import Decimal

from app.adapters.claude import ClaudePort
from app.core.settlement import BonusTerms, Cpm, Tier, validate_terms

SYSTEM = """You convert a brand's description of a performance bonus for a creator deal into \
structured terms. The bonus is paid PER VIDEO, on top of the video's agreed price, based on \
that video's views. Two kinds exist and may be combined:
- CPM: a rate in dollars per 1,000 views, counted only after a view threshold, with a cap in \
dollars per video. Example: "$2 per 1K views after 200K, up to $500" -> rate 2, starts after \
200000, cap 500.
- Tiers: a one-off bonus in dollars once a video reaches a view count. Example: "+$300 at 1M \
views" -> views 1000000, bonus 300. At most 5 tiers, sorted by views.
If there is no CPM, set has_cpm false and the CPM numbers to 0. If the text cannot be \
understood as such terms (no cap given for a CPM, a bonus per deal rather than per video, \
anything ambiguous), put one short question for the brand in `question`; otherwise leave \
`question` empty."""

SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "has_cpm": {"type": "boolean"},
        "cpm_rate_per_1k_dollars": {"type": "number"},
        "cpm_starts_after_views": {"type": "integer"},
        "cpm_cap_dollars": {"type": "number"},
        "tiers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "views": {"type": "integer"},
                    "bonus_dollars": {"type": "number"},
                },
                "required": ["views", "bonus_dollars"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "question",
        "has_cpm",
        "cpm_rate_per_1k_dollars",
        "cpm_starts_after_views",
        "cpm_cap_dollars",
        "tiers",
    ],
    "additionalProperties": False,
}

INVALID = "Those terms don't add up (tiers must rise in views and every amount must be above zero). Could you restate them?"


def _cents(dollars: float) -> int:
    return int((Decimal(str(dollars)) * 100).to_integral_value())


async def parse_bonus_terms(claude: ClaudePort, model: str, text: str) -> BonusTerms | str:
    """The terms, or a question for the brand when they cannot be parsed safely."""
    message = await claude.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": text[:2000]}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if message.get("stop_reason") == "refusal":
        return "I couldn't read those terms. Could you describe the bonus differently?"
    raw = next(b["text"] for b in message["content"] if b.get("type") == "text")
    data = json.loads(raw)
    if data.get("question"):
        return str(data["question"])
    cpm = (
        Cpm(
            _cents(data["cpm_rate_per_1k_dollars"]),
            int(data["cpm_starts_after_views"]),
            _cents(data["cpm_cap_dollars"]),
        )
        if data.get("has_cpm")
        else None
    )
    terms = BonusTerms(
        cpm,
        tuple(Tier(int(t["views"]), _cents(t["bonus_dollars"])) for t in data.get("tiers", [])),
    )
    if validate_terms(terms):
        return INVALID
    return terms

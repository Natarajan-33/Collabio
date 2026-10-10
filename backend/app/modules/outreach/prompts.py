"""What the model is told when it writes an outreach email, and what it hands back.

`OutreachContext` deliberately has no field for the brand's budget ceiling: whatever is not
in the context cannot reach the prompt, the email or an event payload (spec 6.2).
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.money import format_cents
from app.core.package_text import display_label, package_one_liner
from app.modules.threads.repo import ThreadRef
from app.schemas.negotiation import PackageDelta
from app.schemas.packages import ContentType, PackageTerms

OUTREACH_SYSTEM = """\
You write one outreach email from a brand to one content creator about a paid collaboration.

Rules:
- Personalise only from the creator's bio, niches and package as given. Never invent facts \
about the creator.
- State the ask plainly: the number of videos, the format, the price and the go-live date, \
all exactly as given.
- The only prices you may write are the ask price and the creator's own listed prices as \
given. Never mention a budget, a maximum, a ceiling or any other number.
- `subject` is at most 80 characters and names the product. `opener` is at most 2 sentences, \
`ask_paragraph` at most 4, and `rationale` (why this creator fits) at most 2.
- Plain sentences only: no markdown, no greeting line, no sign-off. The template adds those.
"""


class EmailDraft(BaseModel):
    """The parts of the email the model writes; the template supplies the rest."""

    subject: str = Field(max_length=120)
    opener: str
    ask_paragraph: str
    rationale: str


@dataclass(frozen=True)
class OutreachContext:
    thread: ThreadRef
    attempts: int
    reply_token: str
    brand_name: str
    product_name: str
    product_summary: str
    negotiation_ask: str
    deliverables_format: ContentType
    ask_videos: int
    ask_price_cents: int
    go_live_by: date
    flexibility: list[str]
    creator_name: str
    creator_bio: str | None
    creator_niches: list[str]
    creator_email: str | None
    package_id: UUID
    package: PackageTerms
    delta: PackageDelta


def outreach_prompt(ctx: OutreachContext) -> str:
    flexibility = ", ".join(ctx.flexibility) if ctx.flexibility else "none"
    niches = ", ".join(display_label(niche) for niche in ctx.creator_niches) or "not given"
    lines = [
        f"Brand: {ctx.brand_name}",
        f"Product: {ctx.product_name} - {ctx.product_summary}",
        f"What to negotiate for: {ctx.negotiation_ask}",
        f"Flexibility: {flexibility}",
        "",
        f"Creator: {ctx.creator_name}",
        f"Bio: {ctx.creator_bio or 'not given'}",
        f"Niches: {niches}",
        f'Creator package "{ctx.package.name}": {package_one_liner(ctx.package)}',
        "",
        (
            f"The ask: {ctx.ask_videos} {display_label(ctx.deliverables_format)} "
            f"{'video' if ctx.ask_videos == 1 else 'videos'} for "
            f"{format_cents(ctx.ask_price_cents)}, live by {ctx.go_live_by.isoformat()}."
        ),
        (
            f"The creator lists {format_cents(ctx.delta.listed_price_cents)} for "
            f"{ctx.ask_videos} of these. Against their package: {ctx.delta.headline}."
        ),
    ]
    return "\n".join(lines)

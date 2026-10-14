"""What each notification email says. Pure, apart from the polite-decline paragraph.

`compose` turns a `NotifyContext` (loaded per outbox row by the sender) into a
`NotifyContent`: subject, heading, body lines and one call-to-action. Only terms that were
stated in the event itself appear; a private limit (a creator's floor, a brand's ceiling) is
never loaded into the context, so no kind can print one.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.core.contact import first_name
from app.core.money import format_cents
from app.modules.notify.outbox import OutboxKind
from app.schemas.negotiation import NegotiationTerms

CLOSED_FALLBACK = (
    "Thanks for considering {brand}'s offer for {product}. We've decided to go in a "
    "different direction for this campaign, and we hope to work with you on a future one."
)

CLOSED_SYSTEM = (
    "You write one short, warm, professional paragraph (two or three sentences) that a brand "
    "sends a creator when it closes an offer without booking them. Thank the creator for "
    "considering the offer and say you hope to work together on a future campaign. Do not "
    "mention prices, money, other creators, or the reason; do not promise anything specific; "
    "do not use a greeting or a sign-off; write plain text."
)


@dataclass(frozen=True)
class NotifyContext:
    """Everything one notification is written from."""

    kind: OutboxKind
    thread_id: UUID
    batch_id: UUID
    brand_name: str
    product_name: str
    creator_name: str
    creator_first_name: str
    to_address: str | None
    reply_token: str
    outreach_subject: str | None
    terms: NegotiationTerms | None  # the notifying event's terms
    note: str | None
    reason: str | None  # creator's decline reason, or the closed / needs-review reason
    deal_id: UUID | None
    frontend_url: str
    backend_url: str
    inbound_domain: str
    creator_opted_out: bool = False  # the creator unsubscribed; only creator_awarded still goes


class NotifyContent(BaseModel):
    subject: str
    heading: str
    lines: list[str]
    cta_label: str
    cta_url: str
    ai_written: bool = False


class ClosedParagraph(BaseModel):
    paragraph: str = Field(min_length=1, max_length=600)


def _date(day: date) -> str:
    return f"{day:%b} {day.day}, {day.year}"


def _videos(count: int) -> str:
    return f"{count} video" if count == 1 else f"{count} videos"


def terms_line(terms: NegotiationTerms | None, *, with_date: bool = True) -> str:
    """`3 videos · $1,100 · live by Nov 30, 2026`, leaving out whatever the terms lack."""
    if terms is None:
        return ""
    parts: list[str] = []
    if terms.videos is not None:
        parts.append(_videos(terms.videos))
    if terms.price_cents is not None:
        parts.append(format_cents(terms.price_cents))
    if with_date and terms.go_live_by is not None:
        parts.append(f"live by {_date(terms.go_live_by)}")
    return " · ".join(parts)


def _lines(*candidates: str | None) -> list[str]:
    return [line for line in candidates if line]


def compose(ctx: NotifyContext, *, closed_paragraph: str | None = None) -> NotifyContent:
    """The content for `ctx.kind`. `closed_paragraph` is the body of `creator_closed`."""
    frontend = ctx.frontend_url.rstrip("/")
    full_terms = terms_line(ctx.terms)
    short_terms = terms_line(ctx.terms, with_date=False)
    board_url = f"{frontend}/brand/batches/{ctx.batch_id}?thread={ctx.thread_id}"
    their_note = f"Their note: {ctx.note}" if ctx.note else None
    creator = ctx.creator_name

    match ctx.kind:
        case "creator_brand_countered":
            return NotifyContent(
                subject=(
                    f"Re: {ctx.outreach_subject}"
                    if ctx.outreach_subject
                    else f"{ctx.brand_name} sent you a counter-offer"
                ),
                heading=f"{ctx.brand_name} sent a counter-offer",
                lines=_lines(full_terms, their_note),
                cta_label="Review the offer",
                cta_url=f"{frontend}/creator/offers/{ctx.thread_id}",
            )
        case "creator_awarded":
            return NotifyContent(
                subject=f"You're booked: {ctx.brand_name} × {ctx.product_name}",
                heading=f"{ctx.brand_name} booked you for {ctx.product_name}",
                lines=_lines(full_terms, "Your payment milestones and next steps are in the deal."),
                cta_label="View the deal",
                cta_url=(
                    f"{frontend}/creator/deals/{ctx.deal_id}"
                    if ctx.deal_id
                    else f"{frontend}/creator/deals"
                ),
            )
        case "creator_closed":
            paragraph = closed_paragraph or CLOSED_FALLBACK.format(
                brand=ctx.brand_name, product=ctx.product_name
            )
            return NotifyContent(
                subject=f"Update on {ctx.brand_name}'s offer",
                heading=f"An update on {ctx.brand_name}'s offer",
                lines=[paragraph],
                cta_label="See your offers",
                cta_url=f"{frontend}/creator/offers",
            )
        case "brand_creator_countered":
            return NotifyContent(
                subject=(
                    f"{creator} countered: {short_terms}"
                    if short_terms
                    else f"{creator} sent a counter-offer"
                ),
                heading=f"{creator} sent a counter-offer",
                lines=_lines(full_terms, their_note),
                cta_label="Open the board",
                cta_url=board_url,
            )
        case "brand_creator_accepted":
            return NotifyContent(
                subject=f"{creator} accepted your offer",
                heading=f"{creator} accepted your offer",
                lines=_lines(full_terms, "You can award the deal from your board."),
                cta_label="Open the board",
                cta_url=board_url,
            )
        case "brand_creator_declined":
            return NotifyContent(
                subject=f"{creator} declined your offer",
                heading=f"{creator} declined your offer",
                lines=_lines(
                    f"{creator} won't be taking this one on.",
                    f"Their reason: {ctx.reason}" if ctx.reason else None,
                ),
                cta_label="Open the board",
                cta_url=board_url,
            )
        case "brand_needs_review":
            return NotifyContent(
                subject=f"{creator} replied — needs your review",
                heading=f"{creator} replied and needs your review",
                lines=_lines(
                    "Collabio couldn't turn this reply into a clear position, so it's waiting "
                    "for you.",
                    f"Why it needs you: {ctx.reason}" if ctx.reason else None,
                ),
                cta_label="Open the board",
                cta_url=board_url,
            )


def closed_prompt(ctx: NotifyContext) -> str:
    return (
        f"Brand: {ctx.brand_name}\n"
        f"Product: {ctx.product_name}\n"
        f"Creator's first name: {first_name(ctx.creator_name)}\n"
        "Write the paragraph."
    )


async def closed_paragraph(gemini: GeminiPort | None, ctx: NotifyContext) -> tuple[str, bool]:
    """The `creator_closed` body and whether Gemini wrote it.

    Falls back to `CLOSED_FALLBACK` with no Gemini, when it is down or returns something that
    does not fit, or when the text mentions money.
    """
    fallback = CLOSED_FALLBACK.format(brand=ctx.brand_name, product=ctx.product_name)
    if gemini is None:
        return fallback, False
    try:
        reply = await gemini.generate_structured(
            system=CLOSED_SYSTEM, prompt=closed_prompt(ctx), schema=ClosedParagraph
        )
    except (GeminiUnavailable, GeminiInvalidOutput):
        return fallback, False
    text = " ".join(reply.paragraph.split())
    if not text or "$" in text:
        return fallback, False
    return text, True

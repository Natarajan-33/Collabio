"""Pure helpers over `NegotiationTerms`: the brand's offer, agreed terms, and what changed."""

from datetime import date

from app.schemas.deals import AgreedTerms
from app.schemas.negotiation import NegotiationTerms, Stance, TermsChannel, TermsInput
from app.schemas.packages import ContentType

_COMPARED = ("videos", "price_cents", "go_live_by", "format", "conditions", "addons")


class TermsIncomplete(Exception):
    """The latest terms lack a video count or a price, so no deal can be struck on them."""


class GoLiveInPast(Exception):
    """A counter names a go-live date that has already passed."""

    message = "The go-live date has passed"


def ensure_go_live_not_past(t: TermsInput, today: date) -> None:
    """Raise `GoLiveInPast` when the typed terms name a go-live date before `today` (UTC)."""
    if t.go_live_by is not None and t.go_live_by < today:
        raise GoLiveInPast(GoLiveInPast.message)


def brand_offer_terms(
    *,
    ask_videos: int,
    ask_price_cents: int,
    go_live_by: date,
    format: ContentType,
    counter: NegotiationTerms | None,
) -> NegotiationTerms:
    """The brand's current offer: its latest counter over the brief's ask (Ruling 2).

    A counter's missing fields fall back to the ask.
    """
    c = counter
    return NegotiationTerms(
        videos=(c.videos if c else None) or ask_videos,
        format=(c.format if c else None) or format,
        price_cents=(c.price_cents if c else None) or ask_price_cents,
        go_live_by=(c.go_live_by if c else None) or go_live_by,
        conditions=list(c.conditions) if c else [],
        addons=list(c.addons) if c else [],
        stance="offer",
        source="in_app",
        confidence=1.0,
    )


def agreed_terms(
    latest: NegotiationTerms | None, *, brief_format: ContentType, brief_go_live_by: date
) -> AgreedTerms:
    """The complete terms of a deal; the brief fills the format and go-live date left open."""
    if latest is None or latest.videos is None or latest.price_cents is None:
        raise TermsIncomplete("The latest terms need a video count and a price")
    return AgreedTerms(
        videos=latest.videos,
        format=latest.format or brief_format,
        price_cents=latest.price_cents,
        go_live_by=latest.go_live_by or brief_go_live_by,
        conditions=list(latest.conditions),
        addons=list(latest.addons),
    )


def complete_counter(
    terms: NegotiationTerms, brand_offer: NegotiationTerms
) -> NegotiationTerms | None:
    """A creator counter with its video count filled from the brand offer (Ruling 5).

    None when the counter has no price, or neither side names a video count.
    """
    if terms.price_cents is None:
        return None
    if terms.videos is not None:
        return terms
    if brand_offer.videos is None:
        return None
    return terms.model_copy(update={"videos": brand_offer.videos})


def terms_from_input(
    t: TermsInput, *, stance: Stance, source: TermsChannel, format: ContentType
) -> NegotiationTerms:
    """Terms typed into a form, which are certain by definition."""
    return NegotiationTerms(
        videos=t.videos,
        format=format,
        price_cents=t.price_cents,
        go_live_by=t.go_live_by,
        conditions=list(t.conditions),
        stance=stance,
        source=source,
        confidence=1.0,
    )


def terms_changed(a: NegotiationTerms | None, b: NegotiationTerms | None) -> list[str]:
    """The deal fields that differ between two positions; a missing position has no fields."""
    return [f for f in _COMPARED if _value(a, f) != _value(b, f)]


def _value(t: NegotiationTerms | None, field: str):
    if t is None:
        return [] if field in ("conditions", "addons") else None
    return getattr(t, field)

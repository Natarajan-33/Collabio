"""Negotiation guardrails: the counter-offer check against the private ceiling, and who may be called.

`check_counter` is one of the only places the brand's budget ceiling is read. Its verdict hints at
the ceiling, so callers must never store it.
"""

import math
from typing import Literal

from pydantic import BaseModel

from app.core.money import format_cents
from app.schemas.briefs import ChannelPlan
from app.schemas.packages import PreferredChannel

MAX_CALLS_PER_BRAND_PER_DAY = 20


class CounterVerdict(BaseModel):
    """Whether the creator's price fits, and what the agent should say next."""

    verdict: Literal["within", "over"]
    suggested_counter_price_cents: int | None
    talking_point: str


def check_counter(
    *,
    ceiling_cents: int,
    ask_cents: int,
    brief_videos: int,
    offered_price_cents: int,
    offered_videos: int,
    concessions_made: int,
    brand_name: str,
) -> CounterVerdict:
    """Judge an offer against the ceiling scaled to the offered video count.

    Each over-budget verdict closes half the remaining gap between the ask and the ceiling
    (the midpoint, then three quarters, ...), in whole dollars and never above the ceiling.
    """
    scale = offered_videos / brief_videos
    ceiling = math.floor(ceiling_cents * scale)
    ask = min(round(ask_cents * scale), ceiling)
    if offered_price_cents <= ceiling:
        return CounterVerdict(
            verdict="within",
            suggested_counter_price_cents=None,
            talking_point=f"That fits. Agree in principle and say {brand_name} will confirm in writing.",
        )
    step = 1 - 0.5 ** (concessions_made + 1)  # 0.5, 0.75, 0.875, ...
    # Whole dollars, rounded down.
    suggested = (ask + math.floor((ceiling - ask) * step)) // 100 * 100
    suggested = max(min(suggested, ceiling), min(ask, ceiling))
    return CounterVerdict(
        verdict="over",
        suggested_counter_price_cents=suggested,
        talking_point=f"That's above what {brand_name} can do. Offer {format_cents(suggested)} instead.",
    )


def floor_shortfall(
    *, price_cents: int, videos: int, package_volume: int, floor_cents: int
) -> int | None:
    """How far below the creator's floor (scaled up to `videos`, rounded up) a price is, or None.

    Reads the creator's private floor: the caller must not store or return the scaled floor.
    """
    floor = math.ceil(floor_cents * videos / package_volume)
    return floor - price_cents if price_cents < floor else None


def _scaled_ceiling(ceiling_cents: int, videos: int, brief_videos: int) -> int:
    return math.floor(ceiling_cents * videos / brief_videos)


def brand_counter_violation(
    *, price_cents: int, videos: int, brief_videos: int, ceiling_cents: int
) -> str | None:
    """The message for a brand counter above the ceiling scaled to `videos`, or None."""
    ceiling = _scaled_ceiling(ceiling_cents, videos, brief_videos)
    if price_cents <= ceiling:
        return None
    noun = "video" if videos == 1 else "videos"
    return f"Above your ceiling of {format_cents(ceiling)} for {videos} {noun}"


def over_ceiling_cents(
    *, price_cents: int, videos: int, brief_videos: int, ceiling_cents: int
) -> int | None:
    """How far a price is above the ceiling scaled to `videos`, or None when it fits."""
    ceiling = _scaled_ceiling(ceiling_cents, videos, brief_videos)
    return price_cents - ceiling if price_cents > ceiling else None


def call_allowed(phone: str | None, phone_opt_in: bool) -> bool:
    """A creator can be called only with a phone number and an explicit opt-in."""
    return bool(phone and phone.strip()) and phone_opt_in


def default_channel(
    preferred: PreferredChannel, phone: str | None, phone_opt_in: bool
) -> ChannelPlan:
    """Call only a creator who said phone is fine and may be called; everyone else gets email."""
    if preferred == "phone_ok" and call_allowed(phone, phone_opt_in):
        return "call"
    return "email"


def channel_violation(
    plan: ChannelPlan, *, phone: str | None, phone_opt_in: bool, contact_opt_out: bool
) -> str | None:
    """Why `plan` may not be used for this creator, or None."""
    if contact_opt_out:
        return "Opted out of contact"
    if plan in ("call", "email_then_call") and not call_allowed(phone, phone_opt_in):
        return "No phone opt-in"
    return None

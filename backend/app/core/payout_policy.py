"""Whether a computed payout is sent automatically or waits for the brand (spec §6).

This is the only place auto-pay is decided; the settlement agent cannot override it.
"""

from typing import Literal

Decision = Literal["none", "auto", "approval"]
Confidence = Literal["high", "medium", "low"]

CLAIM_TOLERANCE = 0.05


def decide(
    payable: int,
    limit: int,
    view_confidence: Confidence,
    views_read: int,
    claimed_views: int,
    brief_ok: bool,
    disclosure_ok: bool,
) -> Decision:
    if payable <= 0:
        return "none"
    close_to_claim = abs(views_read - claimed_views) <= CLAIM_TOLERANCE * max(claimed_views, 1)
    if (
        payable <= limit
        and views_read > 0  # no readable views is never auto-paid, not even the base
        and claimed_views > 0
        and view_confidence != "low"
        and close_to_claim
        and brief_ok
        and disclosure_ok
    ):
        return "auto"
    return "approval"

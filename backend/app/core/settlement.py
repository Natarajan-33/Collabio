"""The deterministic payout engine (spec §5).

Every amount the settlement agent may move is computed here; the model never supplies one.
All money is integer cents, all rounding is floor.
"""

from dataclasses import dataclass
from typing import Any

FUNDING_MAX_CENTS = 1_000_000
MAX_TIERS = 5


@dataclass(frozen=True)
class Cpm:
    """`rate_cents_per_1k` for every 1,000 views past `starts_after_views`, at most `cap_cents`."""

    rate_cents_per_1k: int
    starts_after_views: int
    cap_cents: int


@dataclass(frozen=True)
class Tier:
    """A one-off `bonus_cents` once a video reaches `views`."""

    views: int
    bonus_cents: int


@dataclass(frozen=True)
class BonusTerms:
    cpm: Cpm | None
    tiers: tuple[Tier, ...]


@dataclass(frozen=True)
class MilestoneState:
    """What the engine needs about one milestone. `best_verified_views` is the high-water
    mark from verified submissions; `committed_cents` is every payout not failed or rejected."""

    amount_cents: int
    verified: bool
    best_verified_views: int
    committed_cents: int


def validate_terms(t: BonusTerms) -> list[str]:
    """Error codes for terms that cannot be funded; empty when valid."""
    errors: list[str] = []
    if t.cpm is not None and (
        t.cpm.rate_cents_per_1k < 1 or t.cpm.cap_cents < 1 or t.cpm.starts_after_views < 0
    ):
        errors.append("non_positive")
    if any(tier.views < 1 or tier.bonus_cents < 1 for tier in t.tiers):
        if "non_positive" not in errors:
            errors.append("non_positive")
    views = [tier.views for tier in t.tiers]
    if len(set(views)) != len(views):
        errors.append("tiers_duplicate")
    elif views != sorted(views):
        errors.append("tiers_unsorted")
    if len(t.tiers) > MAX_TIERS:
        errors.append("too_many_tiers")
    return errors


def _cpm_part(views: int, t: BonusTerms | None) -> int:
    if t is None or t.cpm is None:
        return 0
    over = max(0, views - t.cpm.starts_after_views)
    return min(t.cpm.cap_cents, over * t.cpm.rate_cents_per_1k // 1000)


def _tier_part(views: int, t: BonusTerms | None) -> int:
    if t is None:
        return 0
    return sum(tier.bonus_cents for tier in t.tiers if views >= tier.views)


def bonus_for(views: int, t: BonusTerms | None) -> int:
    return _cpm_part(views, t) + _tier_part(views, t)


def max_bonus_per_video(t: BonusTerms | None) -> int:
    if t is None:
        return 0
    return (t.cpm.cap_cents if t.cpm else 0) + sum(tier.bonus_cents for tier in t.tiers)


def funding_total(amounts: list[int], videos: int, t: BonusTerms | None) -> int:
    """Milestones plus the most every video could earn in bonus; raises `funding_too_large`."""
    total = sum(amounts) + videos * max_bonus_per_video(t)
    if total > FUNDING_MAX_CENTS:
        raise ValueError("funding_too_large")
    return total


def owed(m: MilestoneState, t: BonusTerms | None) -> int:
    return (m.amount_cents if m.verified else 0) + bonus_for(m.best_verified_views, t)


def delta(m: MilestoneState, t: BonusTerms | None) -> int:
    return max(0, owed(m, t) - m.committed_cents)


def available(captured: int, committed_all: int, refunded: int) -> int:
    """Money still held for the deal: captured minus every live payout and every refund."""
    return max(0, captured - committed_all - refunded)


def payable(m: MilestoneState, t: BonusTerms | None, available_cents: int) -> int:
    return max(0, min(delta(m, t), available_cents))


def refund_due(captured: int, committed_all: int, refunded: int) -> int:
    return available(captured, committed_all, refunded)


def breakdown(m: MilestoneState, t: BonusTerms | None) -> dict[str, int]:
    views = m.best_verified_views
    return {
        "base": m.amount_cents if m.verified else 0,
        "cpm": _cpm_part(views, t),
        "tiers": _tier_part(views, t),
        "already_committed": m.committed_cents,
        "delta": delta(m, t),
    }


def terms_to_json(t: BonusTerms) -> dict[str, Any]:
    return {
        "cpm": None
        if t.cpm is None
        else {
            "rate_cents_per_1k": t.cpm.rate_cents_per_1k,
            "starts_after_views": t.cpm.starts_after_views,
            "cap_cents": t.cpm.cap_cents,
        },
        "tiers": [{"views": tier.views, "bonus_cents": tier.bonus_cents} for tier in t.tiers],
    }


def terms_from_json(d: dict[str, Any]) -> BonusTerms:
    cpm = d.get("cpm")
    return BonusTerms(
        Cpm(int(cpm["rate_cents_per_1k"]), int(cpm["starts_after_views"]), int(cpm["cap_cents"]))
        if cpm
        else None,
        tuple(Tier(int(x["views"]), int(x["bonus_cents"])) for x in d.get("tiers", [])),
    )

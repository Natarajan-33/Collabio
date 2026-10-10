"""Best-value ranking of the threads on a brief's board (spec 7.2).

`rank_threads` is one of the only places the brand's budget ceiling is read. It is a pure
function: nothing about the ceiling is stored or returned beyond each thread's verdict.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.schemas.board import BestValue
from app.schemas.negotiation import NegotiationTerms

_RANKABLE_STATUSES = {"countered", "accepted"}
_LATE_DAYS_TO_ZERO = 14
_NO_TERMS = "No creator terms yet"


@dataclass(frozen=True)
class RankInput:
    """One thread's facts for ranking."""

    thread_id: UUID
    status: str
    terms: NegotiationTerms | None
    terms_source: str | None
    engagement_rate: float | None
    similarity: float | None


@dataclass(frozen=True)
class _Eligible:
    thread_id: UUID
    per_video: int
    timeline: float
    engagement: float | None
    similarity: float | None


def _ineligible_reason(item: RankInput, *, ceiling_cents: int, brief_videos: int) -> str | None:
    terms = item.terms
    if (
        item.status not in _RANKABLE_STATUSES
        or item.terms_source != "creator"
        or terms is None
        or terms.price_cents is None
        or terms.videos is None
    ):
        return _NO_TERMS
    if terms.price_cents > ceiling_cents:
        return "Over budget"
    if terms.videos < brief_videos:
        return "Fewer videos than asked"
    return None


def _timeline(terms_go_live: date | None, go_live_by: date) -> float:
    if terms_go_live is None or terms_go_live <= go_live_by:
        return 1.0
    days_late = (terms_go_live - go_live_by).days
    return max(0.0, 1 - days_late / _LATE_DAYS_TO_ZERO)


def _normaliser(values: list[float]):
    """Min-max over `values`; every value maps to 1.0 when they are all equal."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return lambda _v: 1.0
    return lambda v: (v - lo) / (hi - lo)


def rank_threads(
    items: Sequence[RankInput],
    *,
    ceiling_cents: int,
    brief_videos: int,
    go_live_by: date,
) -> dict[UUID, BestValue]:
    """Rank the eligible threads by best value; every input thread gets an entry.

    Score = 0.5 * value ($/video, lower is better) + 0.25 * timeline fit + 0.25 * audience fit,
    each normalised among the eligible threads. Ties go to the higher engagement rate.
    """
    result: dict[UUID, BestValue] = {}
    eligible: list[_Eligible] = []
    for item in items:
        reason = _ineligible_reason(item, ceiling_cents=ceiling_cents, brief_videos=brief_videos)
        if reason is not None:
            result[item.thread_id] = BestValue(
                thread_id=item.thread_id,
                eligible=False,
                rank=None,
                score=None,
                per_video_cents=None,
                reasons=[],
                ineligible_reason=reason,
            )
            continue
        terms = item.terms
        assert terms is not None and terms.price_cents is not None and terms.videos is not None
        eligible.append(
            _Eligible(
                thread_id=item.thread_id,
                per_video=round(terms.price_cents / terms.videos),
                timeline=_timeline(terms.go_live_by, go_live_by),
                engagement=item.engagement_rate,
                similarity=item.similarity,
            )
        )
    if not eligible:
        return result

    pvs = [e.per_video for e in eligible]
    min_pv, max_pv = min(pvs), max(pvs)
    norm_sim = _normaliser([e.similarity for e in eligible if e.similarity is not None] or [0.0])
    norm_eng = _normaliser([e.engagement for e in eligible if e.engagement is not None] or [0.0])

    def value(e: _Eligible) -> float:
        return 1.0 if max_pv == min_pv else (max_pv - e.per_video) / (max_pv - min_pv)

    def audience(e: _Eligible) -> float:
        parts = []
        if e.similarity is not None:
            parts.append(norm_sim(e.similarity))
        if e.engagement is not None:
            parts.append(norm_eng(e.engagement))
        return sum(parts) / len(parts) if parts else 0.5

    audiences = {e.thread_id: audience(e) for e in eligible}
    max_audience = max(audiences.values())
    scores = {
        e.thread_id: round(0.5 * value(e) + 0.25 * e.timeline + 0.25 * audiences[e.thread_id], 4)
        for e in eligible
    }
    ordered = sorted(
        eligible,
        key=lambda e: (-scores[e.thread_id], -(e.engagement or 0.0), str(e.thread_id)),
    )
    for position, e in enumerate(ordered, start=1):
        reasons = []
        if e.per_video == min_pv:
            reasons.append("Lowest $/video")
        if e.timeline == 1.0:
            reasons.append("Meets go-live date")
        if len(eligible) > 1 and audiences[e.thread_id] == max_audience:
            reasons.append("Strongest audience match")
        result[e.thread_id] = BestValue(
            thread_id=e.thread_id,
            eligible=True,
            rank=position,
            score=scores[e.thread_id],
            per_video_cents=e.per_video,
            reasons=reasons,
            ineligible_reason=None,
        )
    return result

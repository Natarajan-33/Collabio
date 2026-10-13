"""Payment milestones: the even split offered at award and the checks on an edited schedule."""

from datetime import date

from app.core.money import format_cents
from app.schemas.deals import AgreedTerms, MilestoneDraft

MIN_AMOUNT_CENTS = 100
MAX_TITLE = 80


def split_even(price_cents: int, videos: int, due: date) -> list[MilestoneDraft]:
    """One milestone per video, all due on `due`; the rounding remainder lands on the last."""
    each = price_cents // videos
    return [
        MilestoneDraft(
            seq=i,
            title=f"Video {i}",
            amount_cents=each if i < videos else price_cents - each * (videos - 1),
            due_date=due,
        )
        for i in range(1, videos + 1)
    ]


def _day(d: date) -> str:
    # Not %-d: that directive is unavailable on Windows.
    return f"{d:%b} {d.day}, {d.year}"


def validate_milestones(agreed: AgreedTerms, drafts: list[MilestoneDraft]) -> list[str]:
    """Why `drafts` cannot pay out `agreed`; empty when they can.

    A wrong count is reported alone: the other checks mean nothing without one milestone per video.
    """
    n = agreed.videos
    if len(drafts) != n:
        return [f"Expected {n} milestones, one per video"]
    errors: list[str] = []
    if sorted(m.seq for m in drafts) != list(range(1, n + 1)):
        errors.append(f"Milestone numbers must run 1 to {n}")
    if any(m.amount_cents < MIN_AMOUNT_CENTS for m in drafts):
        errors.append("Each payment must be at least $1")
    total = sum(m.amount_cents for m in drafts)
    if total != agreed.price_cents:
        errors.append(
            f"Payments add up to {format_cents(total)}, "
            f"not the agreed {format_cents(agreed.price_cents)}"
        )
    errors.extend(
        f"Video {m.seq} is due before the agreed go-live date {_day(agreed.go_live_by)}"
        for m in sorted(drafts, key=lambda m: m.seq)
        if m.due_date < agreed.go_live_by
    )
    if any(not m.title.strip() or len(m.title) > MAX_TITLE for m in drafts):
        errors.append("Every milestone needs a title of at most 80 characters")
    return errors

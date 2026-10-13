"""The thread state machine: which status changes are legal and what events and calls lead to."""

from typing import Literal

from app.schemas.negotiation import NegotiationTerms, Stance, ThreadStatus

# Threads a worker may still pick up or is working on right now.
LIVE_STATUSES = frozenset({"queued", "drafting", "calling", "in_call"})

# Which status a thread may move to from each status. Statuses with no row have no way out.
TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"drafting", "calling", "failed", "closed_lost"}),
    "drafting": frozenset({"awaiting_reply", "failed", "queued"}),  # queued: restart sweep only
    "calling": frozenset(
        {"in_call", "countered", "accepted", "declined", "awaiting_reply", "needs_review", "failed"}
    ),
    "in_call": frozenset(
        {"countered", "accepted", "declined", "awaiting_reply", "needs_review", "failed"}
    ),
    "awaiting_reply": frozenset(
        {
            "failed",
            "countered",
            "accepted",
            "declined",
            "needs_review",
            "no_response",
            "closed_lost",
        }
    ),
    "countered": frozenset(
        {"countered", "awaiting_reply", "awarded", "declined", "closed_lost", "needs_review"}
    ),
    "accepted": frozenset({"awarded", "declined", "closed_lost"}),
    "needs_review": frozenset(
        {"countered", "accepted", "declined", "awaiting_reply", "closed_lost"}
    ),
    "no_response": frozenset(
        {"countered", "accepted", "declined", "needs_review", "awaiting_reply", "closed_lost"}
    ),
    "failed": frozenset({"queued", "closed_lost"}),
}

# Below this, extracted terms are too uncertain to act on and a person must look.
CONFIDENCE_FLOOR = 0.6

_EVENT_STATUS: dict[str, ThreadStatus] = {
    "email_sent": "awaiting_reply",
    "call_started": "in_call",
    "failed": "failed",
    "retried": "queued",
    "needs_review": "needs_review",
    "offer_expired": "no_response",
}
_STANCE_STATUS: dict[str, ThreadStatus] = {
    "counter": "countered",
    "accept": "accepted",
    "decline": "declined",
}


class IllegalTransition(Exception):
    """A status change the state machine does not allow."""


def check_transition(current: str, target: str) -> None:
    """Raise `IllegalTransition` unless `current` may move to `target`."""
    if target not in TRANSITIONS.get(current, frozenset()):
        raise IllegalTransition(f"Cannot move a thread from {current} to {target}")


def status_for_event(event_type: str) -> ThreadStatus | None:
    """The status an event moves its thread to, or None when it leaves the status alone."""
    return _EVENT_STATUS.get(event_type)


def status_after_call(terms: NegotiationTerms | None) -> ThreadStatus:
    """Where a thread lands once its call is over, from the terms extracted from the call."""
    if terms is None or terms.confidence < CONFIDENCE_FLOOR:
        return "needs_review"
    return _STANCE_STATUS.get(terms.stance, "awaiting_reply")


def status_for_stance(stance: Stance, confidence: float) -> ThreadStatus:
    """Where a thread lands after a creator's message, from the stance read out of it.

    Unlike `status_after_call`, anything that is not a clear counter, accept or decline needs a
    person to look: an email that only asks a question has not moved the deal.
    """
    if confidence < CONFIDENCE_FLOOR:
        return "needs_review"
    return _STANCE_STATUS.get(stance, "needs_review")


CreatorAction = Literal["counter", "accept", "decline"]
BrandAction = Literal["counter", "award", "decline", "withdraw", "resolve", "retry"]

_CREATOR_ACTIONS: dict[str, list[CreatorAction]] = {
    "awaiting_reply": ["counter", "accept", "decline"],
    "countered": ["counter", "decline"],
    "accepted": ["decline"],
    "no_response": ["counter", "accept", "decline"],
}
_BRAND_ACTIONS: dict[str, list[BrandAction]] = {
    "queued": ["withdraw"],
    "failed": ["retry", "withdraw"],
    "awaiting_reply": ["withdraw"],
    "countered": ["counter", "award", "decline"],
    "accepted": ["award", "decline"],
    "needs_review": ["resolve", "counter", "decline"],
    "no_response": ["counter", "withdraw"],
}

# Threads whose offer has reached the creator; nothing earlier (or mid-call) is shown to them.
CREATOR_VISIBLE = frozenset(
    {
        "awaiting_reply",
        "countered",
        "accepted",
        "declined",
        "needs_review",
        "awarded",
        "closed_lost",
        "no_response",
        "follow_up_suggested",
    }
)


def creator_actions(status: str) -> list[CreatorAction]:
    """What the creator may do to an offer in this status."""
    return list(_CREATOR_ACTIONS.get(status, []))


def brand_actions(status: str) -> list[BrandAction]:
    """What the brand may do to a thread in this status."""
    return list(_BRAND_ACTIONS.get(status, []))


def waiting_on(status: str) -> Literal["creator", "brand", "none"]:
    """Whose move it is."""
    if status in ("awaiting_reply", "no_response"):
        return "creator"
    if status in ("countered", "accepted", "needs_review"):
        return "brand"
    return "none"

"""The thread state machine: which status changes are legal and what events and calls lead to."""

from app.schemas.negotiation import NegotiationTerms, ThreadStatus

# Threads a worker may still pick up or is working on right now.
LIVE_STATUSES = frozenset({"queued", "drafting", "calling", "in_call"})

# Every other status has no way out in M2 (M3/M4 add rows).
TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"drafting", "calling", "failed"}),
    "drafting": frozenset({"awaiting_reply", "failed", "queued"}),  # queued: restart sweep only
    "calling": frozenset(
        {"in_call", "countered", "accepted", "declined", "awaiting_reply", "needs_review", "failed"}
    ),
    "in_call": frozenset(
        {"countered", "accepted", "declined", "awaiting_reply", "needs_review", "failed"}
    ),
    "awaiting_reply": frozenset({"failed"}),
    "failed": frozenset({"queued"}),
}

# Below this, extracted terms are too uncertain to act on and a person must look.
CONFIDENCE_FLOOR = 0.6

_EVENT_STATUS: dict[str, ThreadStatus] = {
    "email_sent": "awaiting_reply",
    "call_started": "in_call",
    "failed": "failed",
    "retried": "queued",
    "needs_review": "needs_review",
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

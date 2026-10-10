from datetime import date
from typing import get_args

import pytest

from app.core.thread_state import (
    CONFIDENCE_FLOOR,
    LIVE_STATUSES,
    TRANSITIONS,
    IllegalTransition,
    check_transition,
    status_after_call,
    status_for_event,
)
from app.schemas.negotiation import NegotiationTerms, ThreadStatus

T = NegotiationTerms(
    videos=3,
    price_cents=100000,
    go_live_by=date(2026, 11, 1),
    stance="offer",
    source="call",
    confidence=0.9,
)


def test_thread_status_literal_matches_the_migration_order():
    assert get_args(ThreadStatus) == (
        "queued",
        "drafting",
        "awaiting_reply",
        "calling",
        "in_call",
        "countered",
        "accepted",
        "declined",
        "needs_review",
        "failed",
        "awarded",
        "closed_lost",
        "no_response",
        "follow_up_suggested",
    )


@pytest.mark.parametrize(
    "a,b",
    [
        ("queued", "drafting"),
        ("queued", "calling"),
        ("drafting", "awaiting_reply"),
        ("drafting", "queued"),
        ("calling", "in_call"),
        ("calling", "countered"),
        ("in_call", "needs_review"),
        ("failed", "queued"),
    ],
)
def test_allowed(a, b):
    check_transition(a, b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("queued", "awaiting_reply"),
        ("declined", "queued"),
        ("awaiting_reply", "queued"),
        ("in_call", "calling"),
    ],
)
def test_illegal(a, b):
    with pytest.raises(IllegalTransition):
        check_transition(a, b)


def test_terminal_status_has_no_transitions():
    with pytest.raises(IllegalTransition):
        check_transition("accepted", "failed")


def test_live_statuses():
    assert LIVE_STATUSES == {"queued", "drafting", "calling", "in_call"}
    assert set(TRANSITIONS) <= set(get_args(ThreadStatus))


def test_status_for_event():
    events = ("email_sent", "call_started", "failed", "retried", "needs_review", "email_drafted")
    assert [status_for_event(t) for t in events] == [
        "awaiting_reply",
        "in_call",
        "failed",
        "queued",
        "needs_review",
        None,
    ]


@pytest.mark.parametrize(
    "stance,expected",
    [
        ("counter", "countered"),
        ("accept", "accepted"),
        ("decline", "declined"),
        ("offer", "awaiting_reply"),
        ("question", "awaiting_reply"),
        ("no_commitment", "awaiting_reply"),
    ],
)
def test_status_after_call(stance, expected):
    assert status_after_call(T.model_copy(update={"stance": stance})) == expected


def test_low_confidence_needs_review():
    assert CONFIDENCE_FLOOR == 0.6
    assert status_after_call(T.model_copy(update={"confidence": 0.59})) == "needs_review"


def test_confidence_at_the_floor_is_trusted():
    assert status_after_call(T.model_copy(update={"confidence": 0.6})) == "awaiting_reply"


def test_no_terms_needs_review():
    assert status_after_call(None) == "needs_review"

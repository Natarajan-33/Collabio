from datetime import date
from typing import get_args

import pytest

from app.core.thread_state import (
    CONFIDENCE_FLOOR,
    CREATOR_VISIBLE,
    LIVE_STATUSES,
    TRANSITIONS,
    IllegalTransition,
    brand_actions,
    check_transition,
    creator_actions,
    status_after_call,
    status_for_event,
    status_for_stance,
    waiting_on,
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


M2_PAIRS = [
    ("queued", "drafting"),
    ("queued", "calling"),
    ("queued", "failed"),
    ("drafting", "awaiting_reply"),
    ("drafting", "failed"),
    ("drafting", "queued"),
    *[
        (src, dst)
        for src in ("calling", "in_call")
        for dst in (
            "countered",
            "accepted",
            "declined",
            "awaiting_reply",
            "needs_review",
            "failed",
        )
    ],
    ("calling", "in_call"),
    ("awaiting_reply", "failed"),
    ("failed", "queued"),
]

M3_ALLOWED = [
    ("awaiting_reply", "countered"),
    ("awaiting_reply", "accepted"),
    ("awaiting_reply", "declined"),
    ("awaiting_reply", "needs_review"),
    ("awaiting_reply", "no_response"),
    ("awaiting_reply", "closed_lost"),
    ("countered", "countered"),
    ("countered", "awaiting_reply"),
    ("countered", "awarded"),
    ("countered", "declined"),
    ("countered", "closed_lost"),
    ("countered", "needs_review"),
    ("accepted", "awarded"),
    ("accepted", "declined"),
    ("accepted", "closed_lost"),
    ("needs_review", "countered"),
    ("needs_review", "accepted"),
    ("needs_review", "declined"),
    ("needs_review", "awaiting_reply"),
    ("needs_review", "closed_lost"),
    ("no_response", "countered"),
    ("no_response", "accepted"),
    ("no_response", "declined"),
    ("no_response", "needs_review"),
    ("no_response", "awaiting_reply"),
    ("no_response", "closed_lost"),
    ("queued", "closed_lost"),
    ("failed", "closed_lost"),
]
M3_FORBIDDEN = [
    ("awarded", "closed_lost"),
    ("awarded", "countered"),
    ("declined", "countered"),
    ("closed_lost", "awaiting_reply"),
    ("accepted", "countered"),
    ("awaiting_reply", "awarded"),
    ("drafting", "closed_lost"),
    ("calling", "closed_lost"),
    ("in_call", "closed_lost"),
]


@pytest.mark.parametrize("src,dst", M3_ALLOWED)
def test_m3_transition_allowed(src, dst):
    check_transition(src, dst)


@pytest.mark.parametrize("src,dst", M3_FORBIDDEN)
def test_m3_transition_forbidden(src, dst):
    with pytest.raises(IllegalTransition):
        check_transition(src, dst)


@pytest.mark.parametrize("src,dst", M2_PAIRS)
def test_m2_rows_unchanged(src, dst):
    check_transition(src, dst)


@pytest.mark.parametrize(
    "stance,conf,expected",
    [
        ("counter", 0.9, "countered"),
        ("accept", 0.9, "accepted"),
        ("decline", 0.9, "declined"),
        ("question", 0.9, "needs_review"),
        ("no_commitment", 0.9, "needs_review"),
        ("offer", 0.9, "needs_review"),
        ("counter", 0.59, "needs_review"),
    ],
)
def test_status_for_stance(stance, conf, expected):
    assert status_for_stance(stance, conf) == expected


def test_offer_expired_moves_to_no_response():
    assert status_for_event("offer_expired") == "no_response"


@pytest.mark.parametrize(
    "status,creator,brand",
    [
        ("awaiting_reply", ["counter", "accept", "decline"], ["withdraw"]),
        ("countered", ["counter", "decline"], ["counter", "award", "decline"]),
        ("accepted", ["decline"], ["award", "decline"]),
        ("needs_review", [], ["resolve", "counter", "decline"]),
        ("no_response", ["counter", "accept", "decline"], ["counter", "withdraw"]),
        ("queued", [], ["withdraw"]),
        ("failed", [], ["retry", "withdraw"]),
        ("drafting", [], []),
        ("calling", [], []),
        ("in_call", [], []),
        ("awarded", [], []),
        ("declined", [], []),
        ("closed_lost", [], []),
    ],
)
def test_allowed_actions(status, creator, brand):
    assert creator_actions(status) == creator
    assert brand_actions(status) == brand


@pytest.mark.parametrize(
    "status,who",
    [
        ("awaiting_reply", "creator"),
        ("no_response", "creator"),
        ("countered", "brand"),
        ("accepted", "brand"),
        ("needs_review", "brand"),
        ("awarded", "none"),
        ("closed_lost", "none"),
    ],
)
def test_waiting_on(status, who):
    assert waiting_on(status) == who


def test_creator_visible_excludes_unsent():
    assert CREATOR_VISIBLE.isdisjoint({"queued", "drafting", "calling", "in_call", "failed"})

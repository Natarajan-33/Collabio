from datetime import date

import pytest
from pydantic import ValidationError

from app.core.terms import (
    TermsIncomplete,
    agreed_terms,
    brand_offer_terms,
    complete_counter,
    terms_changed,
    terms_from_input,
)
from app.schemas.negotiation import (
    TERMS_EVENT_TYPES,
    NegotiationTerms,
    TermsDraft,
    TermsInput,
)

ASK = {
    "ask_videos": 3,
    "ask_price_cents": 100000,
    "go_live_by": date(2026, 11, 30),
    "format": "short_video",
}


def terms(**kw):
    base = {"stance": "counter", "source": "email", "confidence": 0.9}
    return NegotiationTerms(**{**base, **kw})


def test_brand_offer_is_ask_without_counter():
    t = brand_offer_terms(counter=None, **ASK)
    assert (t.videos, t.price_cents, t.go_live_by, t.format) == (
        3,
        100000,
        date(2026, 11, 30),
        "short_video",
    )
    assert (t.stance, t.source, t.confidence) == ("offer", "in_app", 1.0)


def test_brand_offer_uses_counter():
    t = brand_offer_terms(counter=terms(price_cents=110000, conditions=["No logo"]), **ASK)
    assert (t.videos, t.price_cents, t.go_live_by) == (3, 110000, date(2026, 11, 30))
    assert t.conditions == ["No logo"]
    assert (t.stance, t.source, t.confidence) == ("offer", "in_app", 1.0)


def test_agreed_fills_from_brief():
    a = agreed_terms(
        terms(videos=3, price_cents=120000, stance="accept"),
        brief_format="long_video",
        brief_go_live_by=date(2026, 12, 1),
    )
    assert (a.videos, a.price_cents, a.go_live_by, a.format) == (
        3,
        120000,
        date(2026, 12, 1),
        "long_video",
    )


def test_agreed_prefers_latest_terms():
    a = agreed_terms(
        terms(
            videos=2,
            price_cents=90000,
            format="story",
            go_live_by=date(2026, 12, 20),
            conditions=["c"],
            addons=["a"],
        ),
        brief_format="long_video",
        brief_go_live_by=date(2026, 12, 1),
    )
    assert (a.format, a.go_live_by, a.conditions, a.addons) == (
        "story",
        date(2026, 12, 20),
        ["c"],
        ["a"],
    )


def test_agreed_incomplete_raises():
    kw = {"brief_format": "short_video", "brief_go_live_by": date(2026, 12, 1)}
    with pytest.raises(TermsIncomplete):
        agreed_terms(terms(videos=3), **kw)
    with pytest.raises(TermsIncomplete):
        agreed_terms(terms(price_cents=1000), **kw)
    with pytest.raises(TermsIncomplete):
        agreed_terms(None, **kw)


def test_complete_counter_fills_videos():
    offer = brand_offer_terms(counter=None, **ASK)
    out = complete_counter(terms(price_cents=120000), offer)
    assert out is not None and (out.videos, out.price_cents) == (3, 120000)


def test_complete_counter_keeps_own_videos():
    offer = brand_offer_terms(counter=None, **ASK)
    out = complete_counter(terms(price_cents=120000, videos=2), offer)
    assert out is not None and out.videos == 2


def test_complete_counter_without_price_is_none():
    offer = brand_offer_terms(counter=None, **ASK)
    assert complete_counter(terms(videos=2), offer) is None


def test_terms_from_input():
    t = terms_from_input(
        TermsInput(videos=2, price_cents=5000, go_live_by=date(2026, 12, 1), conditions=["x"]),
        stance="counter",
        source="in_app",
        format="story",
    )
    assert (t.videos, t.price_cents, t.go_live_by, t.format, t.conditions) == (
        2,
        5000,
        date(2026, 12, 1),
        "story",
        ["x"],
    )
    assert (t.stance, t.source, t.confidence) == ("counter", "in_app", 1.0)


def test_terms_changed_lists_fields():
    a = terms(videos=3, price_cents=100000, go_live_by=date(2026, 11, 30))
    b = a.model_copy(update={"price_cents": 110000, "go_live_by": date(2026, 12, 7)})
    assert terms_changed(a, b) == ["price_cents", "go_live_by"]
    assert terms_changed(a, a) == []


def test_terms_changed_order_and_lists():
    a = terms(videos=3)
    b = terms(videos=2, format="story", conditions=["x"], addons=["y"])
    assert terms_changed(a, b) == ["videos", "format", "conditions", "addons"]


def test_terms_changed_with_none():
    assert terms_changed(None, None) == []
    assert terms_changed(None, terms(videos=3, price_cents=5000)) == ["videos", "price_cents"]
    assert terms_changed(terms(videos=3), None) == ["videos"]


@pytest.mark.parametrize(
    "kw",
    [
        {"videos": 0, "price_cents": 1000},
        {"videos": 51, "price_cents": 1000},
        {"videos": 1, "price_cents": 99},
    ],
)
def test_terms_input_bounds(kw):
    with pytest.raises(ValidationError):
        TermsInput(**kw)


def test_terms_input_conditions_limits():
    with pytest.raises(ValidationError):
        TermsInput(videos=1, price_cents=1000, conditions=["x"] * 11)
    with pytest.raises(ValidationError):
        TermsInput(videos=1, price_cents=1000, conditions=["x" * 201])


def test_terms_draft_is_all_optional():
    d = TermsDraft()
    assert (d.videos, d.price_cents, d.go_live_by, d.note, d.conditions) == (
        None,
        None,
        None,
        None,
        [],
    )
    with pytest.raises(ValidationError):
        TermsDraft(note="x" * 1001)
    with pytest.raises(ValidationError):
        TermsDraft(price_cents=99)


def test_terms_event_types():
    assert TERMS_EVENT_TYPES == {
        "email_sent",
        "call_ended",
        "counter_submitted",
        "email_received",
        "accepted",
        "brand_counter_sent",
    }

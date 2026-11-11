"""Auto-pay vs. brand approval: the server-side gate the model cannot talk past."""

from app.core.payout_policy import decide


def call(**overrides):
    args = {
        "payable": 20_000,
        "limit": 30_000,
        "view_confidence": "high",
        "views_read": 400_000,
        "claimed_views": 400_000,
        "brief_ok": True,
        "disclosure_ok": True,
    }
    args.update(overrides)
    return decide(**args)


def test_zero_is_none():
    assert call(payable=0) == "none"


def test_under_limit_all_ok_is_auto():
    assert call() == "auto"
    assert call(payable=30_000) == "auto"
    assert call(view_confidence="medium") == "auto"


def test_over_limit_is_approval():
    assert call(payable=30_001) == "approval"


def test_low_confidence_is_approval():
    assert call(view_confidence="low") == "approval"


def test_claimed_mismatch_over_5pct_is_approval():
    assert call(views_read=812_400, claimed_views=700_000) == "approval"


def test_exactly_5pct_is_auto():
    assert call(views_read=420_000, claimed_views=400_000) == "auto"
    assert call(views_read=380_000, claimed_views=400_000) == "auto"
    assert call(views_read=420_001, claimed_views=400_000) == "approval"


def test_disclosure_or_brief_missing_is_approval():
    assert call(disclosure_ok=False) == "approval"
    assert call(brief_ok=False) == "approval"

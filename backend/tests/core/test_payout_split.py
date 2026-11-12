"""Dashboard base/bonus split per payout (final review minor: cumulative breakdowns double-counted)."""

from app.modules.money.repo import payout_split


def test_first_payout_splits_into_base_and_bonus():
    b = {"base": 60_000, "cpm": 50_000, "tiers": 0, "already_committed": 0, "delta": 110_000}
    assert payout_split(110_000, b) == (60_000, 50_000)


def test_a_later_payout_on_the_same_video_is_all_bonus():
    # More views later: the breakdown is cumulative, the earlier payout already covered the base.
    b = {"base": 60_000, "cpm": 80_000, "tiers": 0, "already_committed": 110_000, "delta": 30_000}
    assert payout_split(30_000, b) == (0, 30_000)


def test_partial_base_and_missing_fields():
    assert payout_split(50_000, {"base": 60_000, "already_committed": 20_000}) == (40_000, 10_000)
    assert payout_split(40_000, {}) == (0, 40_000)

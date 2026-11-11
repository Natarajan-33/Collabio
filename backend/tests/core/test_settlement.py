"""The deterministic payout engine (spec §5): every cent the agent may move comes from here."""

import pytest

from app.core.settlement import (
    BonusTerms,
    Cpm,
    MilestoneState,
    Tier,
    available,
    bonus_for,
    breakdown,
    delta,
    funding_total,
    max_bonus_per_video,
    owed,
    payable,
    refund_due,
    terms_from_json,
    terms_to_json,
    validate_terms,
)

T = BonusTerms(Cpm(200, 200_000, 50_000), (Tier(1_000_000, 30_000),))


@pytest.mark.parametrize(
    ("views", "expected"),
    [
        (150_000, 0),
        (200_000, 0),
        (400_000, 40_000),
        (812_400, 50_000),
        (1_000_000, 80_000),
    ],
)
def test_bonus_for(views, expected):
    assert bonus_for(views, T) == expected


def test_bonus_floors_fractional_cents():
    terms = BonusTerms(Cpm(250, 0, 1_000_000), ())
    assert bonus_for(1_001, terms) == 250  # 1001 * 250 / 1000 = 250.25


def test_no_terms_means_no_bonus():
    assert bonus_for(5_000_000, None) == 0
    assert max_bonus_per_video(None) == 0


def test_tiers_only_terms():
    terms = BonusTerms(None, (Tier(100_000, 5_000), Tier(500_000, 10_000)))
    assert bonus_for(99_999, terms) == 0
    assert bonus_for(100_000, terms) == 5_000
    assert bonus_for(600_000, terms) == 15_000


def test_max_bonus_and_funding_total():
    assert max_bonus_per_video(T) == 80_000
    assert funding_total([40_000, 40_000], 2, T) == 240_000
    assert funding_total([40_000, 40_000], 2, None) == 80_000


def test_funding_total_over_limit_raises():
    with pytest.raises(ValueError, match="funding_too_large"):
        funding_total([600_000, 400_000], 2, T)


def test_owed_and_delta():
    verified = MilestoneState(40_000, True, 400_000, 0)
    assert owed(verified, T) == 80_000
    assert delta(verified, T) == 80_000
    assert delta(MilestoneState(40_000, True, 400_000, 40_000), T) == 40_000
    unverified = MilestoneState(40_000, False, 400_000, 0)
    assert owed(unverified, T) == 40_000  # bonus only; base waits for verification


def test_lower_resubmission_pays_nothing_more():
    # best_verified_views stays at the high-water mark, everything owed already committed
    already = MilestoneState(40_000, True, 812_400, 90_000)
    assert delta(already, T) == 0


def test_delta_never_negative():
    assert delta(MilestoneState(40_000, True, 0, 100_000), T) == 0


def test_payable_clamped_to_available():
    m = MilestoneState(40_000, True, 400_000, 0)
    assert payable(m, T, 10_000) == 10_000
    assert payable(m, T, 1_000_000) == 80_000
    assert payable(m, T, -5) == 0


def test_available_and_refund_due():
    assert available(240_000, 120_000, 0) == 120_000
    assert available(240_000, 120_000, 120_000) == 0
    assert refund_due(240_000, 120_000, 0) == 120_000
    assert refund_due(240_000, 40_000, 0) == 200_000
    assert refund_due(240_000, 240_000, 0) == 0


def test_breakdown_parts():
    m = MilestoneState(40_000, True, 1_000_000, 40_000)
    assert breakdown(m, T) == {
        "base": 40_000,
        "cpm": 50_000,
        "tiers": 30_000,
        "already_committed": 40_000,
        "delta": 80_000,
    }


def test_validate_terms():
    assert validate_terms(T) == []
    unsorted = BonusTerms(None, (Tier(500, 1), Tier(100, 1)))
    assert "tiers_unsorted" in validate_terms(unsorted)
    dup = BonusTerms(None, (Tier(100, 1), Tier(100, 2)))
    assert "tiers_duplicate" in validate_terms(dup)
    many = BonusTerms(None, tuple(Tier(i * 10, 1) for i in range(1, 7)))
    assert "too_many_tiers" in validate_terms(many)
    assert "non_positive" in validate_terms(BonusTerms(Cpm(0, 0, 100), ()))
    assert "non_positive" in validate_terms(BonusTerms(None, (Tier(100, 0),)))
    assert "non_positive" in validate_terms(BonusTerms(Cpm(100, -1, 100), ()))


def test_terms_json_round_trip():
    assert terms_from_json(terms_to_json(T)) == T
    assert terms_to_json(T) == {
        "cpm": {"rate_cents_per_1k": 200, "starts_after_views": 200_000, "cap_cents": 50_000},
        "tiers": [{"views": 1_000_000, "bonus_cents": 30_000}],
    }
    assert terms_from_json({"cpm": None, "tiers": []}) == BonusTerms(None, ())

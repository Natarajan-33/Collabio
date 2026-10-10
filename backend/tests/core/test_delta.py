from datetime import date
from uuid import UUID, uuid4

import pytest

from app.core.delta import compute_delta, delta_headline, listed_price_for, pick_anchor_package
from app.schemas.negotiation import ListedPrice, NegotiationTerms
from app.schemas.packages import Addon, PackageTerms

PID = UUID("00000000-0000-0000-0000-000000000001")
PKG = PackageTerms(
    name="Review Pair",
    content_type="short_video",
    niche="consumer_tech",
    volume_count=2,
    volume_basis="per_contract",
    base_price_cents=100000,
    preferred_channel="email_first",
    addons=[Addon(name="Extra video", price_cents=40000, unit="video")],
    lead_time_days=10,
)
NO_ADDON = PKG.model_copy(update={"addons": []})


def test_listed_price_within_volume_is_base():
    assert listed_price_for(PKG, 2) == ListedPrice(cents=100000, estimated=False)


def test_listed_price_below_volume_is_base():
    assert listed_price_for(PKG, 1) == ListedPrice(cents=100000, estimated=False)


def test_listed_price_uses_video_addon():
    assert listed_price_for(PKG, 3) == ListedPrice(cents=140000, estimated=False)


def test_listed_price_ignores_item_addons():
    item_only = PKG.model_copy(
        update={"addons": [Addon(name="Rush", price_cents=9000, unit="item")]}
    )
    assert listed_price_for(item_only, 3) == ListedPrice(cents=150000, estimated=True)


def test_listed_price_extrapolates_without_addon():
    assert listed_price_for(NO_ADDON, 4) == ListedPrice(cents=200000, estimated=True)


def test_headline_spec_example():
    assert delta_headline(PKG, 3, 100000) == "+1 video vs package · $400 under list (−29%)"


def test_headline_at_list():
    assert delta_headline(PKG, 2, 100000) == "Same videos as package · At list price"


def test_headline_fewer_videos():
    pkg = PKG.model_copy(update={"volume_count": 3, "base_price_cents": 150000})
    assert delta_headline(pkg, 2, 120000) == "−1 video vs package · $300 under list (−20%)"


def test_headline_over_list():
    assert delta_headline(PKG, 2, 110000) == "Same videos as package · $100 over list (+10%)"


def test_headline_estimated_suffix():
    assert delta_headline(NO_ADDON, 4, 200000) == "+2 videos vs package · At list price · estimated"


def test_flags_below_base_and_lead_time():
    d = compute_delta(
        PID,
        PKG,
        ask_videos=2,
        ask_price_cents=90000,
        go_live_by=date(2026, 10, 15),
        today=date(2026, 10, 10),
    )
    assert d.flags == ["below_base_price", "lead_time_conflict"] and d.days_to_go_live == 5


def test_flags_estimated_comes_last():
    d = compute_delta(
        PID,
        NO_ADDON,
        ask_videos=4,
        ask_price_cents=90000,
        go_live_by=date(2026, 10, 15),
        today=date(2026, 10, 10),
    )
    assert d.flags == ["below_base_price", "lead_time_conflict", "estimated"]


def test_no_flags_when_clean():
    d = compute_delta(
        PID,
        PKG,
        ask_videos=2,
        ask_price_cents=100000,
        go_live_by=date(2026, 12, 1),
        today=date(2026, 10, 10),
    )
    assert d.flags == []
    assert d.latest_videos is None and d.latest_price_cents is None
    assert d.latest_per_video_cents is None and d.latest_headline is None


def test_no_lead_time_means_no_conflict():
    pkg = PKG.model_copy(update={"lead_time_days": None})
    d = compute_delta(
        PID,
        pkg,
        ask_videos=2,
        ask_price_cents=100000,
        go_live_by=date(2026, 10, 11),
        today=date(2026, 10, 10),
    )
    assert d.flags == [] and d.lead_time_days is None


def test_per_video_rounding():
    d = compute_delta(
        PID,
        PKG,
        ask_videos=3,
        ask_price_cents=110000,
        go_live_by=date(2026, 12, 1),
        today=date(2026, 10, 10),
    )
    assert (d.ask_per_video_cents, d.listed_per_video_cents) == (36667, 46667)
    assert (
        d.listed_price_cents == 140000 and d.listed_videos == 2 and d.package_name == "Review Pair"
    )


def test_latest_terms_fill_latest_fields():
    latest = NegotiationTerms(
        videos=3, price_cents=120000, stance="counter", source="call", confidence=0.9
    )
    d = compute_delta(
        PID,
        PKG,
        ask_videos=3,
        ask_price_cents=100000,
        go_live_by=date(2026, 12, 1),
        today=date(2026, 10, 10),
        latest=latest,
    )
    assert (
        d.latest_per_video_cents == 40000
        and d.latest_headline == "+1 video vs package · $200 under list (−14%)"
    )
    assert (d.latest_videos, d.latest_price_cents) == (3, 120000)


def test_latest_without_price_is_ignored():
    latest = NegotiationTerms(videos=3, stance="question", source="email", confidence=0.8)
    d = compute_delta(
        PID,
        PKG,
        ask_videos=3,
        ask_price_cents=100000,
        go_live_by=date(2026, 12, 1),
        today=date(2026, 10, 10),
        latest=latest,
    )
    assert d.latest_videos is None and d.latest_headline is None


def _pkg(name: str, content_type: str, volume: int, price: int) -> tuple[UUID, PackageTerms]:
    return uuid4(), PKG.model_copy(
        update={
            "name": name,
            "content_type": content_type,
            "volume_count": volume,
            "base_price_cents": price,
        }
    )


def test_anchor_prefers_format_then_volume_then_price():
    short_far = _pkg("A short far", "short_video", 10, 50000)
    short_near_dear = _pkg("B short near dear", "short_video", 3, 90000)
    short_near_cheap = _pkg("C short near cheap", "short_video", 3, 80000)
    long_exact = _pkg("D long exact", "long_video", 3, 10000)
    packages = [short_far, short_near_dear, long_exact, short_near_cheap]

    # Format wins over volume and price.
    assert pick_anchor_package(packages, fmt="short_video", videos=3) == short_near_cheap
    assert pick_anchor_package(packages, fmt="long_video", videos=10) == long_exact
    # Volume closeness next, within the format.
    assert (
        pick_anchor_package([short_far, short_near_dear], fmt="short_video", videos=9) == short_far
    )
    assert (
        pick_anchor_package([short_far, short_near_dear], fmt="short_video", videos=2)
        == short_near_dear
    )
    # No format: volume then price across all.
    assert pick_anchor_package(packages, fmt=None, videos=3) == long_exact
    assert pick_anchor_package(packages, fmt=None, videos=None) == long_exact
    # Tie on everything but name.
    a, b = _pkg("Alpha", "story", 1, 100), _pkg("Beta", "story", 1, 100)
    assert pick_anchor_package([b, a], fmt=None, videos=None) == a


def test_anchor_empty_raises():
    with pytest.raises(ValueError):
        pick_anchor_package([], fmt=None, videos=None)

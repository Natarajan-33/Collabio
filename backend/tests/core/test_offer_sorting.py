"""Offer sorts (Ruling 7): fit, revenue, timeline, ties newest first."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from app.modules.discovery.service import package_summary
from app.modules.offers.service import sort_offers
from app.schemas.offers import BrandChip, OfferListItem
from app.schemas.packages import PackageTerms

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
PACKAGE = package_summary(
    uuid4(),
    PackageTerms(
        name="Three Shorts",
        content_type="short_video",
        niche="consumer_tech",
        volume_count=3,
        volume_basis="per_contract",
        base_price_cents=90000,
        preferred_channel="email_first",
    ),
)


def item(
    name: str, *, fit_gap=0.0, value=100000, go_live=date(2026, 11, 20), age_minutes=0
) -> OfferListItem:
    return OfferListItem(
        thread_id=uuid4(),
        brand=BrandChip(id=uuid4(), name=name),
        product_name="Pods",
        status="awaiting_reply",
        waiting_on="creator",
        package=PACKAGE,
        delta_headline="Same videos as package",
        delta_flags=[],
        total_value_cents=value,
        go_live_by=go_live,
        expires_at=None,
        updated_at=NOW - timedelta(minutes=age_minutes),
        fit_gap=fit_gap,
    )


def names(items) -> list[str]:
    return [i.brand.name for i in items]


def test_fit_closest_first():
    items = [item("far", fit_gap=0.4), item("exact", fit_gap=0.0), item("near", fit_gap=0.1)]
    assert names(sort_offers(items, "fit")) == ["exact", "near", "far"]


def test_revenue_highest_first():
    items = [item("low", value=50000), item("high", value=300000), item("mid", value=120000)]
    assert names(sort_offers(items, "revenue")) == ["high", "mid", "low"]


def test_timeline_soonest_first():
    items = [
        item("late", go_live=date(2026, 12, 30)),
        item("soon", go_live=date(2026, 11, 1)),
        item("mid", go_live=date(2026, 11, 20)),
    ]
    assert names(sort_offers(items, "timeline")) == ["soon", "mid", "late"]


def test_ties_newest_first():
    items = [item("old", age_minutes=60), item("new", age_minutes=1), item("mid", age_minutes=30)]
    for sort in ("fit", "revenue", "timeline"):
        assert names(sort_offers(items, sort)) == ["new", "mid", "old"]


def test_sort_does_not_mutate_input():
    items = [item("b", fit_gap=0.5), item("a", fit_gap=0.1)]
    sort_offers(items, "fit")
    assert names(items) == ["b", "a"]

"""The package delta engine: how an ask or a counter differs from a creator's listed package."""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from app.core.money import format_cents
from app.core.pricing import extra_video_addon
from app.schemas.negotiation import DeltaFlag, ListedPrice, NegotiationTerms, PackageDelta
from app.schemas.packages import ContentType, PackageTerms


def listed_price_for(pkg: PackageTerms, videos: int) -> ListedPrice:
    """The package's listed price for `videos` videos (spec 7.1).

    Within the package's volume it is the base price; beyond it, the base price plus the
    per-video add-on for each extra video. Without such an add-on the base price per video is
    extrapolated and the result is marked `estimated`.
    """
    if videos <= pkg.volume_count:
        return ListedPrice(cents=pkg.base_price_cents, estimated=False)
    addon = extra_video_addon(pkg)
    if addon is not None:
        extra = (videos - pkg.volume_count) * addon.price_cents
        return ListedPrice(cents=pkg.base_price_cents + extra, estimated=False)
    cents = round(pkg.base_price_cents * videos / pkg.volume_count)
    return ListedPrice(cents=cents, estimated=True)


def _videos_part(pkg: PackageTerms, videos: int) -> str:
    diff = videos - pkg.volume_count
    if diff == 0:
        return "Same videos as package"
    noun = "video" if abs(diff) == 1 else "videos"
    sign = "+" if diff > 0 else "−"
    return f"{sign}{abs(diff)} {noun} vs package"


def _price_part(listed_cents: int, price_cents: int) -> str:
    diff = price_cents - listed_cents
    if diff == 0:
        return "At list price"
    pct = round(abs(diff) / listed_cents * 100)
    if diff < 0:
        return f"{format_cents(-diff)} under list (−{pct}%)"
    return f"{format_cents(diff)} over list (+{pct}%)"


def delta_headline(pkg: PackageTerms, videos: int, price_cents: int) -> str:
    """A one-line summary such as `+1 video vs package · $400 under list (−29%)`."""
    listed = listed_price_for(pkg, videos)
    parts = [_videos_part(pkg, videos), _price_part(listed.cents, price_cents)]
    if listed.estimated:
        parts.append("estimated")
    return " · ".join(parts)


def pick_anchor_package(
    packages: Sequence[tuple[UUID, PackageTerms]],
    *,
    fmt: ContentType | None,
    videos: int | None,
) -> tuple[UUID, PackageTerms]:
    """The package a brief is compared against.

    Prefers the same content type as `fmt`, then the volume closest to `videos`, then the
    lowest base price, then the name.
    """
    if not packages:
        raise ValueError("no packages to choose an anchor from")

    def key(entry: tuple[UUID, PackageTerms]) -> tuple[int, int, int, str]:
        pkg = entry[1]
        other_format = int(fmt is not None and pkg.content_type != fmt)
        volume_gap = abs(pkg.volume_count - videos) if videos is not None else 0
        return (other_format, volume_gap, pkg.base_price_cents, pkg.name)

    return min(packages, key=key)


def compute_delta(
    package_id: UUID,
    pkg: PackageTerms,
    *,
    ask_videos: int,
    ask_price_cents: int,
    go_live_by: date,
    today: date,
    latest: NegotiationTerms | None = None,
) -> PackageDelta:
    """Compare the brief's ask, and the creator's latest terms if any, with the package."""
    listed = listed_price_for(pkg, ask_videos)
    days_to_go_live = (go_live_by - today).days

    latest_videos = latest_price = latest_per_video = latest_headline = None
    if latest is not None and latest.videos is not None and latest.price_cents is not None:
        latest_videos = latest.videos
        latest_price = latest.price_cents
        latest_per_video = round(latest_price / latest_videos)
        latest_headline = delta_headline(pkg, latest_videos, latest_price)

    flags: list[DeltaFlag] = []
    if ask_price_cents < pkg.base_price_cents:
        flags.append("below_base_price")
    if pkg.lead_time_days is not None and days_to_go_live < pkg.lead_time_days:
        flags.append("lead_time_conflict")
    if listed.estimated:
        flags.append("estimated")

    return PackageDelta(
        package_id=package_id,
        package_name=pkg.name,
        listed_videos=pkg.volume_count,
        ask_videos=ask_videos,
        latest_videos=latest_videos,
        listed_price_cents=listed.cents,
        ask_price_cents=ask_price_cents,
        latest_price_cents=latest_price,
        listed_per_video_cents=round(listed.cents / ask_videos),
        ask_per_video_cents=round(ask_price_cents / ask_videos),
        latest_per_video_cents=latest_per_video,
        lead_time_days=pkg.lead_time_days,
        days_to_go_live=days_to_go_live,
        headline=delta_headline(pkg, ask_videos, ask_price_cents),
        latest_headline=latest_headline,
        flags=flags,
    )

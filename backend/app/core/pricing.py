"""Prices derived from a package's terms."""

from app.schemas.packages import Addon, PackageTerms


def extra_video_addon(pkg: PackageTerms) -> Addon | None:
    """The add-on that prices one more video: the first with `unit == "video"`."""
    return next((addon for addon in pkg.addons if addon.unit == "video"), None)


def per_video_cents(pkg: PackageTerms) -> int:
    """Base price spread evenly over the package's videos."""
    return round(pkg.base_price_cents / pkg.volume_count)

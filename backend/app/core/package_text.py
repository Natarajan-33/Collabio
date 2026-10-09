"""Human-readable package text: card one-liners and the creator embedding document."""

import hashlib

from app.core.money import format_cents
from app.core.pricing import extra_video_addon
from app.schemas.packages import PackageTerms

_BASIS_UNIT = {"per_week": "week", "per_contract": "contract"}


def display_label(key: str) -> str:
    """A vocabulary key as words: `b2b_saas` -> `b2b saas`."""
    return key.replace("_", " ")


def _videos(count: int) -> str:
    return f"{count} video" if count == 1 else f"{count} videos"


def package_one_liner(pkg: PackageTerms) -> str:
    """E.g. `2 videos/contract · $1,000 · +1 video $400` (add-on part only if one exists)."""
    parts = [
        f"{_videos(pkg.volume_count)}/{_BASIS_UNIT[pkg.volume_basis]}",
        format_cents(pkg.base_price_cents),
    ]
    addon = extra_video_addon(pkg)
    if addon is not None:
        parts.append(f"+1 video {format_cents(addon.price_cents)}")
    return " · ".join(parts)


def creator_embedding_document(
    name: str, bio: str, niches: list[str], packages: list[PackageTerms]
) -> tuple[str, str]:
    """`(title, text)` to embed for a creator: bio, niche labels, one line per package."""
    lines = [bio.strip(), "Niches: " + ", ".join(display_label(niche) for niche in niches)]
    lines += [
        f"Package: {pkg.name} ({display_label(pkg.content_type)}) · {package_one_liner(pkg)}"
        for pkg in packages
    ]
    return name, "\n".join(line for line in lines if line)


def text_hash(title: str, text: str) -> str:
    """Fingerprint of an embedding document, used to skip re-embedding unchanged text."""
    return hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()

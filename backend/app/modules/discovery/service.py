"""Creator discovery for brands: hybrid semantic + filter search and creator cards.

The database connection is privileged (no RLS) and `repo` selects public columns
only, so everything returned here is safe to show any signed-in brand.
"""

from typing import Any
from uuid import UUID

from app.adapters.db import Database
from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.core.package_text import package_one_liner
from app.core.pricing import per_video_cents
from app.modules.discovery import repo
from app.schemas.discovery import (
    CreatorCard,
    PackageSummary,
    SearchRequest,
    SearchResponse,
)
from app.schemas.packages import PackageTerms


class SearchUnavailable(Exception):
    """The search text could not be embedded, so the semantic ranking is unavailable."""


class DiscoveryService:
    def __init__(self, db: Database, gemini: GeminiPort, *, registered_only: bool = False) -> None:
        self._db = db
        self._gemini = gemini
        self._registered_only = registered_only

    async def search(self, req: SearchRequest) -> SearchResponse:
        """Creators that pass the filters, ranked by meaning when `req.query` is given
        (one embedding request) and by followers otherwise (none).

        Raises `SearchUnavailable` when the query cannot be embedded.
        """
        embedding: list[float] | None = None
        if req.query is not None:
            try:
                embedding = await self._gemini.embed_query(req.query)
            except (GeminiUnavailable, GeminiInvalidOutput) as exc:
                raise SearchUnavailable from exc

        async with self._db.acquire() as conn:
            ids = await repo.match_creator_ids(
                conn,
                embedding=embedding,
                filters=req.filters,
                limit=req.limit,
                registered_only=self._registered_only,
            )
            rows = await repo.fetch_cards(conn, ids, registered_only=self._registered_only)
        return SearchResponse(
            query=req.query, filters=req.filters, results=[_card(row) for row in rows]
        )


async def get_creator(
    db: Database, creator_id: UUID, *, registered_only: bool = False
) -> CreatorCard | None:
    """The creator's card, or None when there is no such creator, none of their packages is
    published (they are not in the marketplace yet) or, with `registered_only`, they have no
    account."""
    async with db.acquire() as conn:
        rows = await repo.fetch_cards(conn, [creator_id], registered_only=registered_only)
    if not rows or not rows[0]["packages"]:
        return None
    return _card(rows[0])


def initials(name: str) -> str:
    """First letter of the first two words: `Arjun Mehta` -> `AM`."""
    return "".join(word[0] for word in name.split()[:2]).upper()


def package_summary(package_id: UUID, terms: PackageTerms) -> PackageSummary:
    """The card text and derived prices for a package's terms."""
    return PackageSummary(
        id=package_id,
        name=terms.name,
        content_type=terms.content_type,
        niche=terms.niche,
        volume_count=terms.volume_count,
        volume_basis=terms.volume_basis,
        base_price_cents=terms.base_price_cents,
        per_video_cents=per_video_cents(terms),
        one_liner=package_one_liner(terms),
        lead_time_days=terms.lead_time_days,
        preferred_channel=terms.preferred_channel,
        addons=terms.addons,
    )


def _package(row: dict[str, Any]) -> PackageSummary:
    return package_summary(row["id"], PackageTerms.model_validate(row))


def _card(row: dict[str, Any]) -> CreatorCard:
    engagement_rate = row["engagement_rate"]
    return CreatorCard(
        id=row["id"],
        handle=row["handle"],
        name=row["name"],
        initials=initials(row["name"]),
        niches=row["niches"],
        region=row["region"],
        followers=row["followers"],
        # numeric -> Decimal; kept in percentage points (5.8 means 5.8%).
        engagement_rate=None if engagement_rate is None else float(engagement_rate),
        packages=[_package(package) for package in row["packages"]],
    )

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.api.deps import CurrentUser, get_db, require_role
from app.modules.offers import service
from app.modules.offers.service import OffersService
from app.schemas.offers import OfferCounts, OfferDesk, OfferListItem, OfferSort, OfferTab

router = APIRouter(tags=["offers"])

OFFER_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "`not_found`"}}


async def my_offers(
    user: Annotated[CurrentUser, Depends(require_role("creator"))],
    db: Annotated[Database, Depends(get_db)],
) -> OffersService:
    """The offers of the signed-in creator."""
    creator_id = await service.find_creator_id(db, user.id)
    if creator_id is None:  # a creator profile without its creator row: onboarding never finished
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return OffersService(db, creator_id)


Offers = Annotated[OffersService, Depends(my_offers)]


def _today():
    return datetime.now(UTC).date()


@router.get("/offers")
async def list_offers(
    offers: Offers, tab: OfferTab | None = None, sort: OfferSort = "fit"
) -> list[OfferListItem]:
    """The offers that have reached the creator, optionally one tab's, sorted."""
    return await offers.list(tab, sort, _today())


@router.get("/offers/counts")
async def offer_counts(offers: Offers) -> OfferCounts:
    """How many offers each tab holds."""
    return await offers.counts()


@router.get("/offers/{thread_id}", responses=OFFER_NOT_FOUND)
async def get_offer(thread_id: UUID, offers: Offers) -> OfferDesk:
    """One offer with its columns, log and the actions open to the creator."""
    try:
        return await offers.desk(thread_id, _today())
    except service.OfferNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from exc

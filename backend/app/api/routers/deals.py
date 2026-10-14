from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.api.deps import CurrentUser, get_db, onboarded_user
from app.modules.briefs import service as briefs_service
from app.modules.deals import service
from app.modules.deals.service import DealsService
from app.modules.offers import service as offers_service
from app.schemas.deals import DealListItem, DealView

router = APIRouter(tags=["deals"])

DEAL_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "`not_found`"}}


async def _party(user: CurrentUser, db: Database) -> tuple[UUID | None, UUID | None]:
    """(brand id, creator id) of the signed-in user: exactly one is set."""
    if user.role == "brand":
        brand_id = await briefs_service.find_brand_id(db, user.id)
        if brand_id is not None:
            return brand_id, None
    else:
        creator_id = await offers_service.find_creator_id(db, user.id)
        if creator_id is not None:
            return None, creator_id
    raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")


@router.get("/deals")
async def list_deals(
    user: Annotated[CurrentUser, Depends(onboarded_user)],
    db: Annotated[Database, Depends(get_db)],
) -> list[DealListItem]:
    """The signed-in brand's or creator's booked deals, newest first."""
    brand_id, creator_id = await _party(user, db)
    deals = DealsService(db)
    if brand_id is not None:
        return await deals.list_for_brand(brand_id)
    assert creator_id is not None
    return await deals.list_for_creator(creator_id)


@router.get("/deals/{deal_id}", responses=DEAL_NOT_FOUND)
async def get_deal(
    deal_id: UUID,
    user: Annotated[CurrentUser, Depends(onboarded_user)],
    db: Annotated[Database, Depends(get_db)],
) -> DealView:
    """One deal with its milestones and both parties' contact emails (the only place they
    cross sides)."""
    brand_id, creator_id = await _party(user, db)
    try:
        return await DealsService(db).get(deal_id, brand_id=brand_id, creator_id=creator_id)
    except service.DealNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from exc

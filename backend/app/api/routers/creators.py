from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.api.deps import CurrentUser, get_db, require_role
from app.config import Settings, get_settings
from app.modules.discovery import service
from app.schemas.discovery import CreatorCard

router = APIRouter(prefix="/creators", tags=["creators"])


@router.get(
    "/{creator_id}",
    responses={status.HTTP_404_NOT_FOUND: {"description": "`creator_not_found`"}},
)
async def read_creator(
    creator_id: UUID,
    _brand: Annotated[CurrentUser, Depends(require_role("brand"))],
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CreatorCard:
    """A creator's public card with their published packages."""
    card = await service.get_creator(db, creator_id, registered_only=not settings.demo_mode)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "creator_not_found")
    return card

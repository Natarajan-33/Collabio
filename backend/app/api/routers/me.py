from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.api.deps import AuthenticatedUser, authenticated_user, get_db
from app.modules.me import service
from app.schemas.me import MeResponse, OnboardingRequest

router = APIRouter(tags=["me"])

# Each route declares the user before the database, so a bad token is a 401 even
# when no database is configured.


@router.get("/me")
async def read_me(
    user: Annotated[AuthenticatedUser, Depends(authenticated_user)],
    db: Annotated[Database, Depends(get_db)],
) -> MeResponse:
    return await service.get_me(db, user.id, user.email)


@router.post(
    "/onboarding",
    responses={status.HTTP_409_CONFLICT: {"description": "`role_locked` or `handle_taken`"}},
)
async def onboard(
    onboarding: OnboardingRequest,
    user: Annotated[AuthenticatedUser, Depends(authenticated_user)],
    db: Annotated[Database, Depends(get_db)],
) -> MeResponse:
    """Choose a role ("I sell products" / "I create content") and set up the account."""
    try:
        return await service.onboard(db, user.id, user.email, onboarding)
    except service.RoleLocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "role_locked") from exc
    except service.HandleTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "handle_taken") from exc

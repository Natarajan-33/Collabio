from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.api.deps import CurrentUser, get_db, require_role
from app.modules.briefs import service
from app.modules.briefs.service import BriefService
from app.schemas.briefs import BriefPatch, BriefPreview, CreateBriefRequest, DealBrief

router = APIRouter(prefix="/briefs", tags=["briefs"])

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "`brief_not_found`"}}


async def my_briefs(
    user: Annotated[CurrentUser, Depends(require_role("brand"))],
    db: Annotated[Database, Depends(get_db)],
) -> BriefService:
    """The briefs of the signed-in brand."""
    brand_id = await service.find_brand_id(db, user.id)
    if brand_id is None:  # a brand profile without its brand row: onboarding never finished
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return BriefService(db, brand_id)


Briefs = Annotated[BriefService, Depends(my_briefs)]


def utc_today() -> date:
    return datetime.now(UTC).date()


@contextmanager
def _http_errors() -> Iterator[None]:
    """Service errors as the responses the brief screens expect."""
    try:
        yield
    except service.BriefNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "brief_not_found") from exc
    except service.BriefLaunched as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "brief_launched") from exc
    except service.InvalidField as exc:
        detail = {"error": "invalid_field", "field": exc.field, "message": exc.message}
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from exc
    except service.UnknownCreators as exc:
        detail = {"error": "unknown_creators", "creator_ids": [str(i) for i in exc.ids]}
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from exc


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "`detail` is `{error: unknown_creators, creator_ids: [...]}`"
        }
    },
)
async def create_brief(req: CreateBriefRequest, briefs: Briefs) -> DealBrief:
    """Start a draft brief for these creators, prefilled from the brand and its product."""
    with _http_errors():
        return await briefs.create(req.creator_ids, utc_today())


@router.get("/{brief_id}", responses=NOT_FOUND)
async def get_brief(brief_id: UUID, briefs: Briefs) -> DealBrief:
    """The brief with what it still needs and which rules it breaks."""
    with _http_errors():
        return await briefs.get(brief_id, utc_today())


@router.patch(
    "/{brief_id}",
    responses=NOT_FOUND
    | {
        status.HTTP_409_CONFLICT: {"description": "`brief_launched`"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "`detail` is `{error: invalid_field, field, message}`"
        },
    },
)
async def update_brief(brief_id: UUID, patch: BriefPatch, briefs: Briefs) -> DealBrief:
    """Change the fields sent; fields left out stay as they are and `null` clears one."""
    with _http_errors():
        return await briefs.patch(brief_id, patch, utc_today())


@router.get("/{brief_id}/preview", responses=NOT_FOUND)
async def preview_brief(brief_id: UUID, briefs: Briefs) -> BriefPreview:
    """Each creator's anchor package, how the brief differs from it, and the default channel."""
    with _http_errors():
        return await briefs.preview(brief_id, utc_today())

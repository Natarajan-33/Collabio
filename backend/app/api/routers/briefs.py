import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.adapters.db import Database
from app.adapters.gemini import GeminiInvalidOutput, GeminiPort, GeminiUnavailable
from app.api.deps import CurrentUser, get_db, optional_gemini, require_role
from app.modules.briefs import service
from app.modules.briefs.launch import ChannelNotAllowed
from app.modules.briefs.service import BriefService
from app.schemas.briefs import (
    BriefPatch,
    BriefPreview,
    CreateBriefRequest,
    DealBrief,
    LaunchRequest,
    LaunchResponse,
)
from app.workers.runtime import wake_orchestrator

logger = logging.getLogger(__name__)

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
    except service.BriefIncomplete as exc:
        detail = {
            "error": "brief_incomplete",
            "missing": exc.missing,
            "violations": [v.model_dump(mode="json") for v in exc.violations],
        }
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from exc
    except ChannelNotAllowed as exc:
        detail = {
            "error": "channel_not_allowed",
            "creator_id": str(exc.creator_id),
            "message": exc.message,
        }
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from exc
    except service.NoCreators as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"error": "no_creators"}
        ) from exc


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


async def _brief_embedding(brief: DealBrief, gemini: GeminiPort | None) -> list[float] | None:
    """The brief's search embedding, or None when Gemini is missing or fails (launching goes on)."""
    if gemini is None:
        logger.warning("No Gemini key: launching without a brief embedding")
        return None
    text = f"{brief.product_name}: {brief.product_summary}. {brief.negotiation_ask}"
    try:
        return await gemini.embed_query(text)
    except (GeminiUnavailable, GeminiInvalidOutput):
        logger.warning("Brief embedding failed: launching without it", exc_info=True)
        return None


@router.post(
    "/{brief_id}/launch",
    status_code=status.HTTP_201_CREATED,
    responses=NOT_FOUND
    | {
        status.HTTP_409_CONFLICT: {"description": "`brief_launched`"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "`detail` is `{error: brief_incomplete, missing, violations}`, "
            "`{error: channel_not_allowed, creator_id, message}` or `{error: no_creators}`"
        },
    },
)
async def launch_brief(
    request: Request,
    brief_id: UUID,
    req: LaunchRequest,
    briefs: Briefs,
    gemini: Annotated[GeminiPort | None, Depends(optional_gemini)],
) -> LaunchResponse:
    """Launch a complete brief: one batch, and a queued negotiation thread per creator."""
    today = utc_today()
    with _http_errors():
        brief = await briefs.get(brief_id, today)
        # Embedded before the launch transaction: a slow Gemini must not hold the brief lock.
        embedding = await _brief_embedding(brief, gemini)
        launched = await briefs.launch(brief_id, req, today=today, embedding=embedding)
    wake_orchestrator(request.app)
    return launched

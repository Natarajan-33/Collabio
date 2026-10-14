from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.adapters.gemini import GeminiPort
from app.api.deps import CurrentUser, get_db, get_gemini, require_role
from app.config import Settings, get_settings
from app.modules.discovery.service import DiscoveryService, SearchUnavailable
from app.schemas.discovery import SearchRequest, SearchResponse

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post(
    "/search",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "`search_unavailable`"}},
)
async def search_creators(
    req: SearchRequest,
    _brand: Annotated[CurrentUser, Depends(require_role("brand"))],
    db: Annotated[Database, Depends(get_db)],
    gemini: Annotated[GeminiPort, Depends(get_gemini)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    """Find creators for a brand: filters narrow the marketplace, `query` ranks by meaning."""
    try:
        return await DiscoveryService(db, gemini, registered_only=not settings.demo_mode).search(
            req
        )
    except SearchUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "search_unavailable") from exc

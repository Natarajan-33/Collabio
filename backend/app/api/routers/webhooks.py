"""Endpoints ElevenLabs calls: the negotiation agent's server tools. No JWT: a shared secret."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.api.deps import get_db, require_tool_secret
from app.modules.negotiation import tools
from app.schemas.negotiation import (
    CheckCounterRequest,
    CheckCounterResponse,
    LogOfferRequest,
    LogOfferResponse,
)

router = APIRouter(
    prefix="/webhooks/elevenlabs/tools",
    tags=["webhooks"],
    dependencies=[Depends(require_tool_secret)],
)

TOOL_ERRORS = {
    status.HTTP_404_NOT_FOUND: {"description": "`thread_not_found`"},
    status.HTTP_409_CONFLICT: {"description": "`thread_not_in_call`"},
}


@router.post("/check-counter", responses=TOOL_ERRORS)
async def check_counter(
    req: CheckCounterRequest, db: Annotated[Database, Depends(get_db)]
) -> CheckCounterResponse:
    try:
        return await tools.check_counter_tool(db, req)
    except tools.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread_not_found") from exc
    except tools.ThreadNotInCall as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "thread_not_in_call") from exc


@router.post("/log-offer", responses=TOOL_ERRORS)
async def log_offer(
    req: LogOfferRequest, db: Annotated[Database, Depends(get_db)]
) -> LogOfferResponse:
    try:
        return await tools.log_offer_tool(db, req)
    except tools.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread_not_found") from exc
    except tools.ThreadNotInCall as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "thread_not_in_call") from exc

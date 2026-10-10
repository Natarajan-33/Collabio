"""Endpoints ElevenLabs calls: the negotiation agent's server tools and the post-call webhook.

The tools are guarded by a shared secret header; the post-call webhook has no JWT and no tool
secret, it is authenticated by the HMAC signature on its body.
"""

import json
import logging
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.adapters.db import Database
from app.adapters.elevenlabs import snapshot_from_payload
from app.adapters.gemini import GeminiPort
from app.api.deps import get_db, optional_gemini, require_tool_secret
from app.config import Settings, get_settings
from app.core.signatures import verify_elevenlabs_signature
from app.modules.negotiation import tools
from app.modules.negotiation.completion import complete_call, complete_intake, fail_call
from app.schemas.negotiation import (
    CheckCounterRequest,
    CheckCounterResponse,
    LogOfferRequest,
    LogOfferResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/elevenlabs", tags=["webhooks"])
tools_router = APIRouter(prefix="/tools", dependencies=[Depends(require_tool_secret)])

TOOL_ERRORS = {
    status.HTTP_404_NOT_FOUND: {"description": "`thread_not_found`"},
    status.HTTP_409_CONFLICT: {"description": "`thread_not_in_call`"},
}
POST_CALL_ERRORS = {
    status.HTTP_401_UNAUTHORIZED: {"description": "`invalid_signature`"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "`webhook_unconfigured`"},
}
FAILURE_REASONS = {"busy": "Line busy.", "no-answer": "No answer."}
CONNECT_FAILED = "Call couldn't connect."


@tools_router.post("/check-counter", responses=TOOL_ERRORS)
async def check_counter(
    req: CheckCounterRequest, db: Annotated[Database, Depends(get_db)]
) -> CheckCounterResponse:
    try:
        return await tools.check_counter_tool(db, req)
    except tools.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread_not_found") from exc
    except tools.ThreadNotInCall as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "thread_not_in_call") from exc


@tools_router.post("/log-offer", responses=TOOL_ERRORS)
async def log_offer(
    req: LogOfferRequest, db: Annotated[Database, Depends(get_db)]
) -> LogOfferResponse:
    try:
        return await tools.log_offer_tool(db, req)
    except tools.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread_not_found") from exc
    except tools.ThreadNotInCall as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "thread_not_in_call") from exc


def _brief_id(data: dict[str, Any]) -> UUID | None:
    """The `brief_id` dynamic variable the browser gave the brief agent, when it is a UUID."""
    client_data = data.get("conversation_initiation_client_data")
    variables = client_data.get("dynamic_variables") if isinstance(client_data, dict) else None
    value = variables.get("brief_id") if isinstance(variables, dict) else None
    try:
        return UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


async def signed_body(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> object:
    """The JSON body of a request ElevenLabs signed; 503 without a secret, 401 on a bad
    signature. The raw bytes are verified before they are parsed. Declared ahead of the
    database in `post_call`, so a forged request never reaches it."""
    raw = await request.body()  # the exact bytes that were signed
    secret = settings.elevenlabs_webhook_secret
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook_unconfigured")
    if not verify_elevenlabs_signature(
        raw, request.headers.get("ElevenLabs-Signature"), secret, now=time.time()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_signature")
    try:
        return json.loads(raw)
    except ValueError:
        return None


@router.post("/post-call", responses=POST_CALL_ERRORS)
async def post_call(
    body: Annotated[object, Depends(signed_body)],
    db: Annotated[Database, Depends(get_db)],
    gemini: Annotated[GeminiPort | None, Depends(optional_gemini)],
) -> dict[str, bool]:
    """A finished call or brief conversation. Every validly signed body answers 200, even one
    we cannot use, so that ElevenLabs stops retrying it."""
    data = body.get("data") if isinstance(body, dict) else None
    conversation_id = data.get("conversation_id") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(conversation_id, str):
        return {"ok": True}

    kind = body.get("type")
    if kind == "post_call_transcription":
        try:
            snapshot = snapshot_from_payload({**data, "status": "done"})
        except (KeyError, TypeError, ValueError):
            logger.warning("Post-call body for %s has an unreadable transcript", conversation_id)
            return {"ok": True}
        if not await complete_call(db, gemini, conversation_id, snapshot):
            await complete_intake(db, conversation_id, snapshot, brief_id=_brief_id(data))
    elif kind == "call_initiation_failure":
        failure = data.get("failure_reason")
        reason = (
            FAILURE_REASONS.get(failure, CONNECT_FAILED)
            if isinstance(failure, str)
            else CONNECT_FAILED
        )
        await fail_call(db, conversation_id, reason)
    return {"ok": True}


router.include_router(tools_router)

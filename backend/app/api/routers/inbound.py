"""The Resend inbound-email webhook: creators' replies to offer emails.

No JWT: the request is authenticated by the Svix signature on its raw body.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.adapters.db import Database
from app.adapters.email import EmailPort, EmailUnavailable
from app.adapters.gemini import GeminiPort
from app.api.deps import get_db, get_email, optional_gemini
from app.config import Settings, get_settings
from app.core.svix import verify_svix
from app.modules.inbound import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/resend", tags=["webhooks"])

INBOUND_ERRORS = {
    status.HTTP_401_UNAUTHORIZED: {"description": "`invalid_signature`"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": "`inbound_unconfigured`, `email_unavailable`"
    },
}


async def signed_event(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, Any]:
    """The JSON body of a request Resend signed (Svix); 503 until the webhook is configured,
    401 on a bad signature. The raw bytes are verified before they are parsed. Declared ahead
    of the database in `inbound`, so a forged request never reaches it."""
    if not settings.resend_webhook_secret or not settings.resend_inbound_domain:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "inbound_unconfigured")
    raw = await request.body()  # the exact bytes that were signed
    headers = request.headers
    if not verify_svix(
        settings.resend_webhook_secret,
        msg_id=headers.get("svix-id", ""),
        timestamp=headers.get("svix-timestamp", ""),
        signature_header=headers.get("svix-signature", ""),
        body=raw,
        now=datetime.now(UTC),
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_signature")
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@router.post("/inbound", responses=INBOUND_ERRORS)
async def inbound(
    event: Annotated[dict[str, Any], Depends(signed_event)],
    db: Annotated[Database, Depends(get_db)],
    email: Annotated[EmailPort, Depends(get_email)],
    gemini: Annotated[GeminiPort | None, Depends(optional_gemini)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """A creator's email reply. Every validly signed event answers 200 with its outcome,
    including ones we cannot use, so that Resend stops retrying; only a body we could not fetch
    answers 503, which Resend retries."""
    try:
        outcome = await service.ingest(
            db, email=email, gemini=gemini, settings=settings, event=event
        )
    except EmailUnavailable as exc:
        logger.warning("Fetching an inbound email failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "email_unavailable") from exc
    return {"outcome": outcome}

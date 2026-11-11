import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.modules.money import usage

logger = logging.getLogger(__name__)

from app.adapters.db import Database
from app.adapters.elevenlabs import CallPlacementFailed, ElevenLabsPort, ElevenLabsUnavailable
from app.adapters.email import EmailPort, EmailRejected
from app.adapters.gemini import GeminiPort
from app.api.deps import (
    CurrentUser,
    get_db,
    get_elevenlabs,
    get_email,
    get_gemini,
    onboarded_user,
    optional_gemini,
)
from app.config import Settings, get_settings
from app.modules.me import service as me_service
from app.modules.voice.service import VoiceService, VoiceUnavailable
from app.modules.voice.try_call import (
    DemoNotConfigured,
    InvalidPhone,
    TryCallRateLimited,
    place_try_call,
)
from app.modules.voice.try_email import TryEmailNotConfigured, send_try_email
from app.schemas.voice import ScribeToken, VoiceCommandRequest, VoiceIntent
from app.schemas.voice_try import TryCallRequest, TryCallResponse, TryEmailRequest, TryEmailResponse

router = APIRouter(prefix="/voice", tags=["voice"])

VOICE_UNAVAILABLE = {status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "`voice_unavailable`"}}


def _placement_error_detail(exc: CallPlacementFailed) -> str:
    msg = str(exc).lower()
    if "unverified" in msg and "trial" in msg:
        return "number_not_verified"
    return "voice_unavailable"


TRY_CALL_ERRORS = {
    status.HTTP_400_BAD_REQUEST: {
        "description": "`invalid_phone` or `number_not_verified` (Twilio trial)"
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {"description": "`try_call_rate_limited`"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": "`voice_unavailable` or `demo_not_configured`"
    },
}


@router.post("/scribe-token", responses=VOICE_UNAVAILABLE)
async def scribe_token(
    user: Annotated[CurrentUser, Depends(onboarded_user)],
    elevenlabs: Annotated[ElevenLabsPort, Depends(get_elevenlabs)],
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ScribeToken:
    """A single-use token the browser exchanges for a realtime speech-to-text session."""
    await usage.consume(db, user.id, "voice_session", settings)
    try:
        return await elevenlabs.mint_scribe_token()
    except ElevenLabsUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "voice_unavailable") from exc


@router.post("/command", responses=VOICE_UNAVAILABLE)
async def voice_command(
    req: VoiceCommandRequest,
    _user: Annotated[CurrentUser, Depends(onboarded_user)],
    gemini: Annotated[GeminiPort, Depends(get_gemini)],
) -> VoiceIntent:
    """Turn what the user said into the one action the screen they are on should take."""
    try:
        return await VoiceService(gemini).route(req)
    except VoiceUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "voice_unavailable") from exc


@router.post("/try-call", responses=TRY_CALL_ERRORS)
async def try_call(
    req: TryCallRequest,
    user: Annotated[CurrentUser, Depends(onboarded_user)],
    db: Annotated[Database, Depends(get_db)],
    elevenlabs: Annotated[ElevenLabsPort, Depends(get_elevenlabs)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TryCallResponse:
    """Place a sample negotiation call to the given number. The phone is not stored."""
    if settings.hackathon_mode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "disabled_in_demo")
    me = await me_service.get_me(db, user.id, user.email)
    try:
        await place_try_call(
            db,
            elevenlabs=elevenlabs,
            settings=settings,
            initiator_id=user.id,
            display_name=me.display_name,
            phone=req.phone,
            scenario_id=req.scenario,
            today=datetime.now(UTC).date(),
        )
    except InvalidPhone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_phone")
    except TryCallRateLimited:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "try_call_rate_limited")
    except DemoNotConfigured as exc:
        logger.warning("try_call unavailable (demo): %s", exc or "demo_not_configured")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "demo_not_configured")
    except CallPlacementFailed as exc:
        logger.warning("try_call placement failed: %s", exc)
        detail = _placement_error_detail(exc)
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if detail == "number_not_verified"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise HTTPException(status_code, detail)
    except ElevenLabsUnavailable as exc:
        logger.warning("try_call ElevenLabs down: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "voice_unavailable")

    role = me.role or "brand"
    if role == "brand":
        message = (
            "Our AI agent is calling you now. Answer and play the creator — "
            "you'll hear how Collabio negotiates on a brand's behalf."
        )
    else:
        message = (
            "Our AI agent is calling you now with a sample brand offer. "
            "Answer and respond like you would to a real sponsorship inquiry."
        )
    return TryCallResponse(message=message)


TRY_EMAIL_ERRORS = {
    status.HTTP_400_BAD_REQUEST: {"description": "`invalid_email` or `reserved_email`"},
    status.HTTP_429_TOO_MANY_REQUESTS: {"description": "`try_email_rate_limited`"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": "`email_not_configured` or `email_unavailable`"
    },
}


@router.post("/try-email", responses=TRY_EMAIL_ERRORS)
async def try_email(
    req: TryEmailRequest,
    user: Annotated[CurrentUser, Depends(onboarded_user)],
    db: Annotated[Database, Depends(get_db)],
    gemini: Annotated[GeminiPort | None, Depends(optional_gemini)],
    email: Annotated[EmailPort, Depends(get_email)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TryEmailResponse:
    """Send a sample negotiation outreach email. The address is not stored on the profile."""
    me = await me_service.get_me(db, user.id, user.email)

    try:
        subject = await send_try_email(
            db,
            gemini=gemini,
            email=email,
            settings=settings,
            initiator_id=user.id,
            display_name=me.display_name,
            to_email=req.email,
            scenario_id=req.scenario,
            today=datetime.now(UTC).date(),
        )
    except ValueError as exc:
        if str(exc) == "reserved_email":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reserved_email")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_email")
    except TryCallRateLimited:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "try_email_rate_limited")
    except DemoNotConfigured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "demo_not_configured")
    except TryEmailNotConfigured as exc:
        logger.warning("try_email unavailable: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "email_not_configured")
    except EmailRejected as exc:
        logger.warning("try_email rejected: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "email_rejected")

    return TryEmailResponse(
        message=f"We sent a sample outreach email to {req.email}. Subject: “{subject}”. "
        "Check your inbox (and spam). This address was not saved in Collabio."
    )

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.elevenlabs import ElevenLabsPort, ElevenLabsUnavailable
from app.adapters.gemini import GeminiPort
from app.api.deps import CurrentUser, get_elevenlabs, get_gemini, onboarded_user
from app.modules.voice.service import VoiceService, VoiceUnavailable
from app.schemas.voice import ScribeToken, VoiceCommandRequest, VoiceIntent

router = APIRouter(prefix="/voice", tags=["voice"])

VOICE_UNAVAILABLE = {status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "`voice_unavailable`"}}


@router.post("/scribe-token", responses=VOICE_UNAVAILABLE)
async def scribe_token(
    _user: Annotated[CurrentUser, Depends(onboarded_user)],
    elevenlabs: Annotated[ElevenLabsPort, Depends(get_elevenlabs)],
) -> ScribeToken:
    """A single-use token the browser exchanges for a realtime speech-to-text session."""
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

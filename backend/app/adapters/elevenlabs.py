"""ElevenLabs adapter: single-use tokens that let the browser stream speech to Scribe.

Services depend on `ElevenLabsPort`; `ElevenLabsClient` implements it over the elevenlabs SDK.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from elevenlabs import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError

from app.config import Settings
from app.schemas.voice import ScribeToken

REQUEST_TIMEOUT_SECONDS = 10.0
# ElevenLabs documents single-use tokens as valid for 15 minutes but does not return the
# expiry, so it is derived from the time of the request (taken before it, to err early).
TOKEN_LIFETIME = timedelta(minutes=15)


class ElevenLabsUnavailable(Exception):
    """ElevenLabs did not hand out a token: a network or API error."""


class ElevenLabsPort(Protocol):
    async def mint_scribe_token(self) -> ScribeToken:
        """A token for one realtime Scribe session, spent on first use."""
        ...


class ElevenLabsClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.elevenlabs_api_key:
            raise ValueError("ELEVENLABS_API_KEY is not set")
        self._client = AsyncElevenLabs(
            api_key=settings.elevenlabs_api_key, timeout=REQUEST_TIMEOUT_SECONDS
        )

    async def mint_scribe_token(self) -> ScribeToken:
        requested_at = datetime.now(UTC)
        try:
            response = await self._client.tokens.single_use.create(token_type="realtime_scribe")
        except (ApiError, httpx.TransportError) as exc:
            raise ElevenLabsUnavailable(f"ElevenLabs token request failed: {exc}") from exc
        return ScribeToken(
            token=response.token, expires_at=(requested_at + TOKEN_LIFETIME).isoformat()
        )

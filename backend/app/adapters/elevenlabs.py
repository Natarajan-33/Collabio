"""ElevenLabs adapter: Scribe tokens, agent conversation tokens, outbound calls, transcripts.

Services depend on `ElevenLabsPort`; `ElevenLabsClient` implements it over the elevenlabs SDK.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from elevenlabs import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError
from elevenlabs.types import ConversationInitiationClientDataRequestInput
from pydantic import BaseModel

from app.config import Settings
from app.schemas.negotiation import TranscriptTurn
from app.schemas.voice import ScribeToken

REQUEST_TIMEOUT_SECONDS = 10.0
# ElevenLabs documents single-use tokens as valid for 15 minutes but does not return the
# expiry, so it is derived from the time of the request (taken before it, to err early).
TOKEN_LIFETIME = timedelta(minutes=15)


class ElevenLabsUnavailable(Exception):
    """ElevenLabs did not answer: a network or API error."""


class CallPlacementFailed(Exception):
    """ElevenLabs refused the call; `str(exc)` is its message."""


class ConversationSnapshot(BaseModel):
    """A conversation as we store it. `status` is one of initiated, in-progress,
    processing, done, failed."""

    conversation_id: str
    status: str
    turns: list[TranscriptTurn]
    duration_secs: int | None
    summary: str | None

    @property
    def user_spoke(self) -> bool:
        return any(t.role == "user" and t.text.strip() for t in self.turns)


def snapshot_from_payload(data: dict[str, Any]) -> ConversationSnapshot:
    """Reduce an ElevenLabs conversation (SDK response dumped to JSON, or a webhook's `data`).

    Only spoken turns are kept, as `{role, text, t}`. Tool calls and tool results are
    dropped: a `check_counter` result reveals the brand's private ceiling, and transcripts
    are creator-readable.
    """
    turns: list[TranscriptTurn] = []
    for item in data.get("transcript") or []:
        message = item.get("message")
        if item.get("role") not in ("agent", "user") or not isinstance(message, str):
            continue
        if not message.strip():
            continue
        turns.append(
            TranscriptTurn(role=item["role"], text=message.strip(), t=item["time_in_call_secs"])
        )
    metadata = data.get("metadata") or {}
    analysis = data.get("analysis") or {}
    return ConversationSnapshot(
        conversation_id=data["conversation_id"],
        status=data["status"],
        turns=turns,
        duration_secs=metadata.get("call_duration_secs"),
        summary=analysis.get("transcript_summary"),
    )


class ElevenLabsPort(Protocol):
    async def mint_scribe_token(self) -> ScribeToken:
        """A token for one realtime Scribe session, spent on first use."""
        ...

    async def mint_conversation_token(self, agent_id: str) -> str:
        """A WebRTC token for the browser to start a conversation with `agent_id`."""
        ...

    async def place_call(
        self,
        *,
        agent_id: str,
        phone_number_id: str,
        to_number: str,
        dynamic_variables: dict[str, str],
    ) -> str:
        """Dial `to_number` with the agent; the conversation id.

        Raises `CallPlacementFailed` when ElevenLabs refuses the call.
        """
        ...

    async def get_conversation(self, conversation_id: str) -> ConversationSnapshot: ...


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

    async def mint_conversation_token(self, agent_id: str) -> str:
        try:
            response = await self._client.conversational_ai.conversations.get_webrtc_token(
                agent_id=agent_id
            )
        except (ApiError, httpx.TransportError) as exc:
            raise ElevenLabsUnavailable(f"ElevenLabs conversation token failed: {exc}") from exc
        return response.token

    async def place_call(
        self,
        *,
        agent_id: str,
        phone_number_id: str,
        to_number: str,
        dynamic_variables: dict[str, str],
    ) -> str:
        try:
            response = await self._client.conversational_ai.twilio.outbound_call(
                agent_id=agent_id,
                agent_phone_number_id=phone_number_id,
                to_number=to_number,
                conversation_initiation_client_data=ConversationInitiationClientDataRequestInput(
                    dynamic_variables=dict(dynamic_variables)
                ),
            )
        except (ApiError, httpx.TransportError) as exc:
            raise ElevenLabsUnavailable(f"ElevenLabs call request failed: {exc}") from exc
        if not response.success or not response.conversation_id:
            raise CallPlacementFailed(response.message)
        return response.conversation_id

    async def get_conversation(self, conversation_id: str) -> ConversationSnapshot:
        try:
            response = await self._client.conversational_ai.conversations.get(
                conversation_id=conversation_id
            )
        except (ApiError, httpx.TransportError) as exc:
            raise ElevenLabsUnavailable(f"ElevenLabs conversation fetch failed: {exc}") from exc
        return snapshot_from_payload(response.model_dump(mode="json"))

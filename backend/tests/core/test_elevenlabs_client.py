"""ElevenLabsClient against a mocked ElevenLabs REST API (respx)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from elevenlabs.core.api_error import ApiError
from elevenlabs.types import TokenResponseModel, TwilioOutboundCallResponse
from fastapi import HTTPException

from app.adapters.elevenlabs import CallPlacementFailed, ElevenLabsClient, ElevenLabsUnavailable
from app.api import deps
from app.config import Settings

TOKEN_URL = "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, elevenlabs_api_key="test-key")


async def test_mints_a_realtime_scribe_token_that_expires_in_fifteen_minutes(settings, respx_mock):
    route = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"token": "sutkn_abc"})
    )
    before = datetime.now(UTC)

    scribe = await ElevenLabsClient(settings).mint_scribe_token()

    [call] = route.calls
    assert call.request.headers["xi-api-key"] == "test-key"
    assert scribe.token == "sutkn_abc"
    expires_at = datetime.fromisoformat(scribe.expires_at)
    assert expires_at.tzinfo is not None
    assert before + timedelta(minutes=15) <= expires_at <= datetime.now(UTC) + timedelta(minutes=15)


@pytest.mark.parametrize("status", [401, 422])
async def test_an_api_error_is_unavailable(settings, respx_mock, status):
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(status, json={"detail": "no"}))
    with pytest.raises(ElevenLabsUnavailable):
        await ElevenLabsClient(settings).mint_scribe_token()


async def test_a_network_failure_is_unavailable(settings, respx_mock):
    respx_mock.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("unreachable"))
    with pytest.raises(ElevenLabsUnavailable):
        await ElevenLabsClient(settings).mint_scribe_token()


def test_a_missing_api_key_is_a_value_error():
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        ElevenLabsClient(Settings(_env_file=None, elevenlabs_api_key=""))


def test_the_dependency_without_an_api_key_is_503(monkeypatch):
    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(_env_file=None, elevenlabs_api_key="")
    )
    deps.get_elevenlabs.cache_clear()
    try:
        with pytest.raises(HTTPException) as caught:
            deps.get_elevenlabs()
    finally:
        deps.get_elevenlabs.cache_clear()
    assert caught.value.status_code == 503
    assert caught.value.detail == "elevenlabs_unavailable"


# Agent calls and conversations ----------------------------------------------------


class StubTwilio:
    def __init__(self, response: TwilioOutboundCallResponse | Exception) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def outbound_call(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class StubConversations:
    def __init__(self) -> None:
        self.token_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.get_response = None

    async def get_webrtc_token(self, **kwargs):
        self.token_calls.append(kwargs)
        return TokenResponseModel(token="rtc_tok", conversation_id="conv_x")

    async def get(self, conversation_id, **kwargs):
        self.get_calls.append(conversation_id)
        return self.get_response


def stubbed(settings, *, twilio=None, conversations=None) -> ElevenLabsClient:
    client = ElevenLabsClient(settings)
    client._client = SimpleNamespace(
        conversational_ai=SimpleNamespace(twilio=twilio, conversations=conversations)
    )
    return client


async def test_place_call_passes_dynamic_variables(settings):
    twilio = StubTwilio(
        TwilioOutboundCallResponse(success=True, message="ok", conversation_id="conv_9")
    )

    conversation_id = await stubbed(settings, twilio=twilio).place_call(
        agent_id="agent_1",
        phone_number_id="phnum_1",
        to_number="+14155550100",
        dynamic_variables={"creator_first_name": "Priya", "brand_name": "Lumen"},
    )

    assert conversation_id == "conv_9"
    [call] = twilio.calls
    assert call["agent_id"] == "agent_1"
    assert call["agent_phone_number_id"] == "phnum_1"
    assert call["to_number"] == "+14155550100"
    assert call["conversation_initiation_client_data"].dynamic_variables == {
        "creator_first_name": "Priya",
        "brand_name": "Lumen",
    }


async def test_place_call_is_never_retried_by_the_sdk(settings):
    # A 5xx after the call was dialed would otherwise be retried and ring the creator again.
    twilio = StubTwilio(
        TwilioOutboundCallResponse(success=True, message="ok", conversation_id="conv_9")
    )

    await stubbed(settings, twilio=twilio).place_call(
        agent_id="a", phone_number_id="p", to_number="+14155550100", dynamic_variables={}
    )

    [call] = twilio.calls
    assert call["request_options"] == {"max_retries": 0}


async def test_place_call_unsuccessful_raises_call_placement_failed(settings):
    twilio = StubTwilio(TwilioOutboundCallResponse(success=False, message="Number is invalid"))
    with pytest.raises(CallPlacementFailed, match="Number is invalid"):
        await stubbed(settings, twilio=twilio).place_call(
            agent_id="a", phone_number_id="p", to_number="+1", dynamic_variables={}
        )


async def test_place_call_without_a_conversation_id_is_a_failure(settings):
    twilio = StubTwilio(TwilioOutboundCallResponse(success=True, message="queued"))
    with pytest.raises(CallPlacementFailed, match="queued"):
        await stubbed(settings, twilio=twilio).place_call(
            agent_id="a", phone_number_id="p", to_number="+1", dynamic_variables={}
        )


async def test_place_call_sdk_error_is_unavailable(settings):
    twilio = StubTwilio(ApiError(status_code=500, body="boom"))
    with pytest.raises(ElevenLabsUnavailable):
        await stubbed(settings, twilio=twilio).place_call(
            agent_id="a", phone_number_id="p", to_number="+1", dynamic_variables={}
        )


async def test_mint_conversation_token_returns_token(settings):
    conversations = StubConversations()
    token = await stubbed(settings, conversations=conversations).mint_conversation_token("agent_1")
    assert token == "rtc_tok"
    assert conversations.token_calls == [{"agent_id": "agent_1"}]


async def test_mint_conversation_token_network_error_is_unavailable(settings, respx_mock):
    respx_mock.get("https://api.elevenlabs.io/v1/convai/conversation/token").mock(
        side_effect=httpx.ConnectError("unreachable")
    )
    with pytest.raises(ElevenLabsUnavailable):
        await ElevenLabsClient(settings).mint_conversation_token("agent_1")


async def test_get_conversation_maps_snapshot(settings, respx_mock):
    route = respx_mock.get("https://api.elevenlabs.io/v1/convai/conversations/conv_1").mock(
        return_value=httpx.Response(
            200,
            json={
                "agent_id": "agent_1",
                "conversation_id": "conv_1",
                "status": "done",
                "has_audio": False,
                "has_user_audio": False,
                "has_response_audio": False,
                "has_auxiliary_audio": False,
                "transcript": [
                    {"role": "agent", "message": "Hi Priya", "time_in_call_secs": 0},
                    {
                        "role": "agent",
                        "message": None,
                        "time_in_call_secs": 4,
                        "tool_calls": [],
                        "tool_results": [],
                    },
                    {"role": "user", "message": "Sure", "time_in_call_secs": 6},
                ],
                "metadata": {"start_time_unix_secs": 1, "call_duration_secs": 42},
                "analysis": {
                    "call_successful": "success",
                    "transcript_summary": "Agreed to talk.",
                },
            },
        )
    )

    snapshot = await ElevenLabsClient(settings).get_conversation("conv_1")

    assert route.called
    assert snapshot.conversation_id == "conv_1"
    assert snapshot.status == "done"
    assert snapshot.duration_secs == 42
    assert snapshot.summary == "Agreed to talk."
    assert [(t.role, t.text, t.t) for t in snapshot.turns] == [
        ("agent", "Hi Priya", 0.0),
        ("user", "Sure", 6.0),
    ]
    assert snapshot.user_spoke is True


async def test_get_conversation_api_error_is_unavailable(settings, respx_mock):
    respx_mock.get("https://api.elevenlabs.io/v1/convai/conversations/nope").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    with pytest.raises(ElevenLabsUnavailable):
        await ElevenLabsClient(settings).get_conversation("nope")

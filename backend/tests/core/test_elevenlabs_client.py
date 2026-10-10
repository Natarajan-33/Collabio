"""ElevenLabsClient against a mocked ElevenLabs REST API (respx)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException

from app.adapters.elevenlabs import ElevenLabsClient, ElevenLabsUnavailable
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

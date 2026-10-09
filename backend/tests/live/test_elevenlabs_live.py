"""ElevenLabsClient against the real ElevenLabs API (needs ELEVENLABS_API_KEY)."""

from datetime import UTC, datetime

import pytest

from app.adapters.elevenlabs import ElevenLabsClient
from app.config import Settings


@pytest.fixture(autouse=True)
def require_elevenlabs_key(settings: Settings) -> None:
    if not settings.elevenlabs_api_key:
        pytest.skip("ELEVENLABS_API_KEY is not set")


@pytest.mark.live
async def test_mint_scribe_token(settings):
    scribe = await ElevenLabsClient(settings).mint_scribe_token()

    assert isinstance(scribe.token, str) and scribe.token.strip()
    assert datetime.fromisoformat(scribe.expires_at) > datetime.now(UTC)

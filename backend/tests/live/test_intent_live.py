"""The intent router against the real Gemini API (needs GEMINI_API_KEY)."""

import pytest

from app.adapters.gemini import GeminiClient
from app.config import Settings
from app.modules.voice.service import VoiceService
from app.schemas.voice import VoiceCommandRequest, VoiceContext, VoiceIntent


@pytest.fixture(autouse=True)
def require_gemini_key(settings: Settings) -> None:
    if not settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY is not set")


async def route(settings: Settings, screen: str, transcript: str, **context) -> VoiceIntent:
    req = VoiceCommandRequest(screen=screen, transcript=transcript, context=VoiceContext(**context))
    return await VoiceService(GeminiClient(settings)).route(req)


@pytest.mark.live
@pytest.mark.parametrize(
    ("phrase", "cents"),
    [
        ("under two grand", 200000),
        ("below 1.5k", 150000),
        ("max twelve hundred dollars", 120000),
        ("under two thousand dollars", 200000),
    ],
)
async def test_spoken_money_to_cents(settings, phrase, cents):
    intent = await route(settings, "discover", f"tech creators doing short videos {phrase}")

    assert intent.kind == "search"
    assert intent.search.filters.max_price_cents == cents

"""Package dictation against the real Gemini API (needs GEMINI_API_KEY)."""

from uuid import uuid4

import pytest

from app.adapters.db import Database
from app.adapters.gemini import GeminiClient
from app.config import Settings
from app.modules.packages.service import MyCreator, PackageService
from app.schemas.packages import DraftFromSpeechRequest

TRANSCRIPT = (
    "um so call it Weekly Reviews, it's three short videos a week for twelve hundred dollars, "
    "a thumbnail pack is fifty bucks extra, five day lead time, and email only please"
)


@pytest.fixture(autouse=True)
def require_gemini_key(settings: Settings) -> None:
    if not settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY is not set")


@pytest.mark.live
async def test_dictation_fills_the_fields_that_were_said_and_nothing_else(settings):
    creator = MyCreator(id=uuid4(), name="Priya Raman", bio=None, niches=["consumer_tech"])
    packages = PackageService(Database(), creator)  # drafting never touches the database

    result = await packages.draft_from_speech(
        GeminiClient(settings), DraftFromSpeechRequest(transcript=TRANSCRIPT)
    )

    draft = result.draft
    assert draft.name is not None and draft.name.lower() == "weekly reviews"
    assert (draft.content_type, draft.volume_count, draft.volume_basis) == (
        "short_video",
        3,
        "per_week",
    )
    assert draft.base_price_cents == 120000
    assert draft.lead_time_days == 5
    assert draft.preferred_channel == "email_only"
    assert [item.price_cents for item in (*draft.extras, *draft.addons)] == [5000]
    assert draft.niche is None  # never said, so never guessed
    assert result.missing == ["niche"]
    assert "um" not in result.heard.lower().split()

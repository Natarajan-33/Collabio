"""The intent router against the real Gemini API (needs GEMINI_API_KEY)."""

from uuid import UUID

import pytest

from app.adapters.gemini import GeminiClient
from app.config import Settings
from app.modules.voice.service import VoiceService
from app.schemas.voice import CreatorRef, VoiceCommandRequest, VoiceContext, VoiceIntent


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


@pytest.mark.live
async def test_select_by_spoken_names(settings):
    maya = CreatorRef(id=UUID(int=1), name="Maya Chen", handle="mayamakestech")
    arjun = CreatorRef(id=UUID(int=2), name="Arjun Mehta", handle="arjuntech")

    intent = await route(
        settings,
        "discover",
        "um select Maya and uh Arjun mehta",
        visible_creators=[maya, arjun],
    )

    assert intent.kind == "select"
    assert intent.select.creator_ids == [maya.id, arjun.id]


@pytest.mark.live
async def test_package_dictation_fills_only_what_was_said(settings):
    intent = await route(
        settings,
        "packages",
        "three short videos a week for twelve hundred dollars, "
        "add a thumbnail pack for fifty bucks, five day lead time",
    )

    assert intent.kind == "package_draft"
    draft = intent.package_draft
    assert (draft.content_type, draft.volume_count, draft.volume_basis) == (
        "short_video",
        3,
        "per_week",
    )
    assert draft.base_price_cents == 120000
    assert draft.lead_time_days == 5
    assert [item.price_cents for item in (*draft.extras, *draft.addons)] == [5000]
    assert draft.name is None and draft.niche is None and draft.preferred_channel is None


@pytest.mark.live
async def test_spoken_region_becomes_a_stored_code(settings):
    # Regions are stored as US/IN/UK/CA/AU: "India" would match no creator.
    intent = await route(settings, "discover", "tech creators in India under two grand")

    assert intent.kind == "search"
    assert intent.search.filters.region == "IN"
    assert intent.search.filters.max_price_cents == 200000


@pytest.mark.live
async def test_readme_demo_phrase_fills_the_package_draft(settings):
    intent = await route(
        settings,
        "packages",
        "short videos, tech, two per contract for nine hundred, extra video three fifty, "
        "email first",
    )

    assert intent.kind == "package_draft"
    draft = intent.package_draft
    assert (draft.content_type, draft.niche) == ("short_video", "consumer_tech")
    assert (draft.volume_count, draft.volume_basis) == (2, "per_contract")
    assert draft.base_price_cents == 90000
    assert draft.preferred_channel == "email_first"
    # "Extra video" is an add-on counted per video, not one of the non-deliverable extras.
    (addon,) = draft.addons
    assert "extra video" in addon.name.lower()
    assert (addon.price_cents, addon.unit) == (35000, "video")
    assert draft.extras == []
    assert draft.name is None  # never said: the one field the creator still has to fill

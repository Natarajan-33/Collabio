"""Dictating a package: what the model is told, and how its reply is folded into the draft.

Offline: drafting never touches the database, so the service gets an unconnected one.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.adapters.db import Database
from app.adapters.gemini import GeminiInvalidOutput, GeminiUnavailable
from app.modules.packages.prompts import DRAFT_SYSTEM
from app.modules.packages.service import DraftUnavailable, MyCreator, PackageService
from app.modules.voice.prompts import MONEY_AND_VOCAB_RULES
from app.schemas.packages import (
    Addon,
    DraftFromSpeechRequest,
    Extra,
    ExtractedDraft,
    PackageDraft,
)
from tests.fakes import FakeGemini


@pytest.fixture
def gemini() -> FakeGemini:
    return FakeGemini()


@pytest.fixture
def packages() -> PackageService:
    creator = MyCreator(id=uuid4(), name="Test Creator", bio=None, niches=["consumer_tech"])
    return PackageService(Database(), creator)


def request(transcript: str = "um two videos", **current) -> DraftFromSpeechRequest:
    return DraftFromSpeechRequest(transcript=transcript, current=PackageDraft(**current))


def reply(heard: str = "two videos", **draft) -> ExtractedDraft:
    return ExtractedDraft(heard=heard, draft=PackageDraft(**draft))


async def test_the_model_gets_the_shared_money_rules_and_the_whole_situation(gemini, packages):
    gemini.queue_structured(reply())

    await packages.draft_from_speech(gemini, request("add a thumbnail pack", name="Launch Duo"))

    [(system, prompt, schema)] = gemini.calls
    assert schema is ExtractedDraft
    assert system == DRAFT_SYSTEM and MONEY_AND_VOCAB_RULES in system
    assert '"name":"Launch Duo"' in prompt
    assert 'Transcript: "add a thumbnail pack"' in prompt


async def test_an_empty_draft_is_described_as_none(gemini, packages):
    gemini.queue_structured(reply())

    await packages.draft_from_speech(gemini, request("hello"))

    assert "Current package draft: none" in gemini.calls[0][1]


async def test_what_was_said_is_merged_into_the_open_draft(gemini, packages):
    gemini.queue_structured(
        reply(
            "three videos a week for twelve hundred",
            volume_count=3,
            volume_basis="per_week",
            base_price_cents=120000,
            extras=[Extra(name="Thumbnail pack", price_cents=5000)],
        )
    )
    current = {
        "name": "Weekly",
        "extras": [Extra(name="Raw footage", price_cents=30000)],
        "volume_count": 2,
    }

    result = await packages.draft_from_speech(gemini, request(**current))

    draft = result.draft
    assert (draft.name, draft.volume_count, draft.volume_basis) == ("Weekly", 3, "per_week")
    assert draft.base_price_cents == 120000
    assert [e.name for e in draft.extras] == ["Raw footage", "Thumbnail pack"]
    assert result.missing == ["content_type", "niche", "preferred_channel"]
    assert result.heard == "three videos a week for twelve hundred"


async def test_heard_falls_back_to_the_transcript_when_the_model_leaves_it_blank(gemini, packages):
    gemini.queue_structured(reply(heard="  "))

    result = await packages.draft_from_speech(gemini, request("um two videos"))

    assert result.heard == "um two videos"


async def test_violations_cover_the_values_already_said(gemini, packages):
    gemini.queue_structured(
        reply(
            niche="beauty",
            addons=[Addon(name="Rush", price_cents=0, unit="item")],
        )
    )

    result = await packages.draft_from_speech(gemini, request())

    assert [v.field for v in result.violations] == ["niche", "addons"]
    assert "niche" not in result.missing


async def test_unusable_reply_returns_the_draft_unchanged_with_the_transcript(gemini, packages):
    gemini.queue_structured({"heard": "x", "draft": {"volume_count": "lots"}})

    result = await packages.draft_from_speech(gemini, request("blah blah", name="Duo"))

    assert result.draft == PackageDraft(name="Duo")
    assert result.heard == "blah blah"
    assert result.missing[0] == "content_type"


async def test_model_down_is_draft_unavailable(packages):
    class Down:
        async def generate_structured(self, **_):
            raise GeminiUnavailable("down")

    with pytest.raises(DraftUnavailable):
        await packages.draft_from_speech(Down(), request())


async def test_request_side_schema_bugs_propagate_instead_of_looking_like_a_bad_reply(packages):
    # pydantic rejecting our own schema is a bug in this service, not the model's fault.
    class Broken:
        async def generate_structured(self, **_):
            PackageDraft.model_validate({"niche": "not_a_niche"})  # raises ValidationError

    with pytest.raises(ValidationError):
        await packages.draft_from_speech(Broken(), request())


async def test_invalid_output_is_the_only_model_failure_treated_as_a_bad_reply(packages):
    class Garbled:
        async def generate_structured(self, **_):
            raise GeminiInvalidOutput("no JSON")

    result = await packages.draft_from_speech(Garbled(), request("hello"))

    assert result.heard == "hello"


@pytest.mark.parametrize("transcript", ["", "   ", "x" * 1001])
def test_the_transcript_must_have_words_and_stay_bounded(transcript):
    with pytest.raises(ValidationError):
        DraftFromSpeechRequest(transcript=transcript)

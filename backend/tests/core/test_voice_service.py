"""VoiceService against FakeGemini: what it keeps, forces to unclear, and resolves."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.adapters.gemini import GeminiInvalidOutput, GeminiUnavailable
from app.modules.voice.prompts import MONEY_AND_VOCAB_RULES, ROUTER_SYSTEM
from app.modules.voice.service import MAX_SUGGESTIONS, VoiceService, VoiceUnavailable
from app.schemas.discovery import SearchFilters, SearchRequest
from app.schemas.packages import Addon, PackageDraft
from app.schemas.voice import (
    ALLOWED_INTENTS,
    CreatorRef,
    RoutedIntent,
    RoutedSelect,
    VoiceCommandRequest,
    VoiceContext,
    VoiceScreen,
)
from tests.fakes import FakeGemini

MAYA = CreatorRef(id=uuid4(), name="Maya Chen", handle="mayatech")
ARJUN = CreatorRef(id=uuid4(), name="Arjun Mehta", handle="arjuntech")


def request(
    screen: VoiceScreen = "discover", transcript: str = "um do the thing", **context
) -> VoiceCommandRequest:
    return VoiceCommandRequest(
        screen=screen, transcript=transcript, context=VoiceContext(**context)
    )


async def route(fake: FakeGemini, req: VoiceCommandRequest, reply: RoutedIntent | dict):
    fake.queue_structured(reply)
    return await VoiceService(fake).route(req)


@pytest.fixture
def gemini() -> FakeGemini:
    return FakeGemini()


# What the model is told -----------------------------------------------------


async def test_the_model_is_given_the_rules_and_the_whole_situation(gemini):
    draft = PackageDraft(name="Launch Duo", base_price_cents=100_000)
    req = request(
        "packages", "make it twelve hundred", visible_creators=[MAYA], package_draft=draft
    )

    await route(gemini, req, RoutedIntent(kind="unclear", heard="x"))

    [(system, prompt, schema)] = gemini.calls
    assert schema is RoutedIntent
    assert system == ROUTER_SYSTEM and MONEY_AND_VOCAB_RULES in system
    assert "Screen: packages" in prompt and "allowed: navigate, package_draft" in prompt
    assert "Maya Chen (@mayatech)" in prompt
    assert '"name":"Launch Duo"' in prompt and '"base_price_cents":100000' in prompt
    assert "make it twelve hundred" in prompt


def test_the_system_prompt_states_the_vocabularies_and_money_rules():
    for key in ("consumer_tech", "b2b_saas", "short_video", "per_contract", "email_first"):
        assert key in ROUTER_SYSTEM
    for rule in ("integer number of US cents", "max_price_cents", "top_n", "creator_names"):
        assert rule in ROUTER_SYSTEM
    for screen, kinds in ALLOWED_INTENTS.items():
        assert f"- {screen}: {', '.join(sorted(kinds))}" in ROUTER_SYSTEM


# Intents --------------------------------------------------------------------


async def test_search_passes_through_with_the_cleaned_transcript(gemini):
    search = SearchRequest(query="short reviews", filters=SearchFilters(max_price_cents=200_000))
    reply = RoutedIntent(kind="search", heard=" short reviews under 2k ", search=search)

    intent = await route(gemini, request(), reply)

    assert intent.kind == "search" and intent.heard == "short reviews under 2k"
    assert intent.search == search
    assert intent.select is None and intent.package_draft is None


async def test_blank_heard_falls_back_to_the_transcript(gemini):
    reply = RoutedIntent(kind="open_review", heard="  ")
    intent = await route(gemini, request(transcript="open review"), reply)
    assert (intent.kind, intent.heard) == ("open_review", "open review")


@pytest.mark.parametrize("screen", ["discover", "review"])
@pytest.mark.parametrize("kind", ["clear_selection", "open_review"])
async def test_payload_free_intents_on_the_comparison_screens(gemini, screen, kind):
    intent = await route(gemini, request(screen), RoutedIntent(kind=kind, heard="x"))
    assert intent.kind == kind


async def test_select_resolves_names_and_drops_unknown_ones(gemini):
    reply = RoutedIntent(
        kind="select",
        heard="select maya and arjun mehtaa",
        select=RoutedSelect(creator_names=["maya", "Arjun Mehtaa", "Zed"]),
    )
    intent = await route(gemini, request(visible_creators=[MAYA, ARJUN]), reply)
    assert intent.kind == "select"
    assert intent.select.creator_ids == [MAYA.id, ARJUN.id]
    assert intent.select.top_n is None


async def test_select_top_n_needs_no_names(gemini):
    reply = RoutedIntent(kind="select", heard="top ten", select=RoutedSelect(top_n=10))
    intent = await route(gemini, request(), reply)
    assert intent.select.creator_ids == [] and intent.select.top_n == 10


async def test_select_naming_nobody_on_screen_is_unclear(gemini):
    select = RoutedSelect(creator_names=["Zed"])
    reply = RoutedIntent(kind="select", heard="select zed", select=select)

    intent = await route(gemini, request(visible_creators=[MAYA]), reply)

    assert intent.kind == "unclear" and intent.heard == "select zed"
    assert intent.select is None and intent.suggestions


async def test_package_draft_merges_onto_the_open_draft(gemini):
    current = PackageDraft(
        name="Launch Duo",
        base_price_cents=100_000,
        addons=[Addon(name="Extra video", price_cents=40_000, unit="video")],
    )
    said = PackageDraft(
        base_price_cents=120_000,
        addons=[Addon(name="Thumbnail pack", price_cents=5_000, unit="item")],
    )
    reply = RoutedIntent(kind="package_draft", heard="x", package_draft=said)

    intent = await route(gemini, request("packages", package_draft=current), reply)

    assert intent.kind == "package_draft"
    assert intent.package_draft.name == "Launch Duo"
    assert intent.package_draft.base_price_cents == 120_000
    assert [a.name for a in intent.package_draft.addons] == ["Extra video", "Thumbnail pack"]


async def test_package_draft_with_no_open_draft_is_just_what_was_said(gemini):
    said = PackageDraft(niche="beauty", volume_count=3)
    reply = RoutedIntent(kind="package_draft", heard="x", package_draft=said)

    intent = await route(gemini, request("packages"), reply)

    assert intent.package_draft == said


async def test_navigate_to_a_known_page(gemini):
    reply = RoutedIntent(kind="navigate", heard="go to my packages", navigate="/creator/packages")
    intent = await route(gemini, request("any"), reply)
    assert (intent.kind, intent.navigate) == ("navigate", "/creator/packages")


async def test_a_route_outside_the_app_is_unclear(gemini):
    reply = {"kind": "navigate", "heard": "go to admin", "navigate": "https://evil.example/admin"}
    intent = await route(gemini, request("any"), reply)
    assert intent.kind == "unclear" and intent.navigate is None


# Unclear --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("screen", "kind"),
    [
        ("discover", "package_draft"),
        ("review", "package_draft"),
        ("packages", "search"),
        ("packages", "select"),
        ("packages", "open_review"),
        ("any", "search"),
        ("any", "package_draft"),
    ],
)
async def test_an_intent_the_screen_does_not_allow_is_unclear(gemini, screen, kind):
    reply = RoutedIntent(
        kind=kind,
        heard="x",
        search=SearchRequest(),
        select=RoutedSelect(top_n=3),
        package_draft=PackageDraft(),
    )
    intent = await route(gemini, request(screen), reply)
    assert intent.kind == "unclear"
    assert intent.search is None and intent.select is None and intent.package_draft is None


@pytest.mark.parametrize("kind", ["search", "select", "package_draft", "navigate"])
async def test_an_intent_missing_its_payload_is_unclear(gemini, kind):
    screen = "packages" if kind == "package_draft" else "discover"
    intent = await route(gemini, request(screen), RoutedIntent(kind=kind, heard="x"))
    assert intent.kind == "unclear" and intent.suggestions


async def test_the_models_own_suggestions_are_kept_up_to_three(gemini):
    reply = RoutedIntent(kind="unclear", heard="mumble", suggestions=["a", "b", "c", "d"])
    intent = await route(gemini, request(), reply)
    assert intent.suggestions == ["a", "b", "c"] and MAX_SUGGESTIONS == 3


@pytest.mark.parametrize("screen", ["discover", "review", "packages", "any"])
async def test_no_suggestions_from_the_model_falls_back_to_screen_examples(gemini, screen):
    intent = await route(gemini, request(screen), RoutedIntent(kind="unclear", heard="mumble"))
    assert 2 <= len(intent.suggestions) <= MAX_SUGGESTIONS


async def test_data_the_schema_rejects_is_unclear_and_echoes_the_transcript(gemini):
    reply = {"kind": "search", "heard": "x", "search": {"filters": {"max_price_cents": -5}}}
    with pytest.raises(ValidationError):  # what the fake raises, as the SDK would for a reply
        RoutedIntent.model_validate(reply)

    intent = await route(gemini, request(transcript="cheap ones"), reply)

    assert intent.kind == "unclear" and intent.heard == "cheap ones"
    assert intent.suggestions


async def test_gemini_invalid_output_is_unclear():
    class Garbled:
        async def generate_structured(self, **_):
            raise GeminiInvalidOutput("no JSON")

    intent = await VoiceService(Garbled()).route(request(transcript="blah"))
    assert (intent.kind, intent.heard) == ("unclear", "blah")
    assert intent.suggestions


async def test_gemini_unavailable_is_voice_unavailable():
    class Down:
        async def generate_structured(self, **_):
            raise GeminiUnavailable("down")

    with pytest.raises(VoiceUnavailable):
        await VoiceService(Down()).route(request())

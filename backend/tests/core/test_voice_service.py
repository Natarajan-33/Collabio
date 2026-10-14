"""VoiceService against FakeGemini: what it keeps, forces to unclear, and resolves."""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.adapters.gemini import GeminiInvalidOutput, GeminiUnavailable
from app.modules.voice.prompts import MONEY_AND_VOCAB_RULES, ROUTER_SYSTEM
from app.modules.voice.service import MAX_SUGGESTIONS, VoiceService, VoiceUnavailable
from app.schemas.discovery import SearchFilters, SearchRequest
from app.schemas.negotiation import TermsDraft
from app.schemas.packages import Addon, PackageDraft
from app.schemas.voice import (
    ALLOWED_INTENTS,
    CreatorRef,
    OfferRef,
    RoutedIntent,
    RoutedSelect,
    VoiceCommandRequest,
    VoiceContext,
    VoiceScreen,
)
from tests.fakes import FakeGemini

MAYA = CreatorRef(id=uuid4(), name="Maya Chen", handle="mayatech")
ARJUN = CreatorRef(id=uuid4(), name="Arjun Mehta", handle="arjuntech")
PRIYA = CreatorRef(id=uuid4(), name="Priya Nair", handle="priyanair")


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


# Board and brief ------------------------------------------------------------


async def test_open_thread_resolves_a_visible_creator(gemini):
    reply = RoutedIntent(kind="open_thread", heard="open Priya's thread", open_thread_name="priya")

    intent = await route(gemini, request("board", visible_creators=[PRIYA, ARJUN]), reply)

    assert intent.kind == "open_thread"
    assert intent.open_thread.creator_id == PRIYA.id
    assert intent.sort is None and intent.navigate is None


async def test_open_thread_for_an_unknown_name_is_unclear(gemini):
    reply = RoutedIntent(kind="open_thread", heard="open Zed's thread", open_thread_name="zed")

    intent = await route(gemini, request("board", visible_creators=[PRIYA, ARJUN]), reply)

    assert intent.kind == "unclear" and intent.open_thread is None and intent.suggestions


async def test_open_thread_without_a_name_is_unclear(gemini):
    intent = await route(gemini, request("board"), RoutedIntent(kind="open_thread", heard="x"))
    assert intent.kind == "unclear"


@pytest.mark.parametrize("key", ["best_value", "price", "status", "recent"])
async def test_sort_passes_through(gemini, key):
    reply = RoutedIntent(kind="sort", heard="sort by price", sort=key)
    intent = await route(gemini, request("board"), reply)
    assert (intent.kind, intent.sort) == ("sort", key)


async def test_sort_without_a_key_is_unclear(gemini):
    intent = await route(gemini, request("board"), RoutedIntent(kind="sort", heard="sort"))
    assert intent.kind == "unclear"


async def test_open_thread_is_not_allowed_on_discover(gemini):
    reply = RoutedIntent(kind="open_thread", heard="open Priya's thread", open_thread_name="priya")

    intent = await route(gemini, request("discover", visible_creators=[PRIYA]), reply)

    assert intent.kind == "unclear" and intent.open_thread is None


async def test_the_brief_screen_only_navigates(gemini):
    reply = RoutedIntent(kind="sort", heard="sort by price", sort="price")
    intent = await route(gemini, request("brief"), reply)
    assert intent.kind == "unclear" and intent.sort is None


async def test_go_to_the_board_navigates_from_the_brief(gemini):
    reply = RoutedIntent(kind="navigate", heard="go to the board", navigate="/brand/batches")
    intent = await route(gemini, request("brief"), reply)
    assert (intent.kind, intent.navigate) == ("navigate", "/brand/batches")


def test_the_board_and_brief_allow_their_own_intents():
    assert ALLOWED_INTENTS["brief"] == {"navigate"}
    assert ALLOWED_INTENTS["board"] == {
        "open_thread",
        "sort",
        "counter",
        "award",
        "decline",
        "navigate",
    }
    assert ALLOWED_INTENTS["offers"] == {"open_offer", "navigate"}
    assert ALLOWED_INTENTS["offer_desk"] == {"counter", "accept", "decline", "navigate"}
    assert ALLOWED_INTENTS["any"] == {"navigate"}


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


@pytest.mark.parametrize("screen", ["discover", "review", "packages", "any", "brief", "board"])
async def test_no_suggestions_from_the_model_falls_back_to_screen_examples(gemini, screen):
    intent = await route(gemini, request(screen), RoutedIntent(kind="unclear", heard="mumble"))
    assert 2 <= len(intent.suggestions) <= MAX_SUGGESTIONS


async def test_data_the_schema_rejects_is_unclear_and_echoes_the_transcript(gemini):
    reply = {"kind": "search", "heard": "x", "search": {"filters": {"max_price_cents": -5}}}
    with pytest.raises(ValidationError):  # the reply really does break the schema
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


async def test_a_pydantic_error_from_our_own_request_is_a_bug_not_unclear():
    class RejectsOurSchema:
        async def generate_structured(self, **_):
            # e.g. the SDK refusing a keyword in RoutedIntent's JSON schema
            RoutedIntent.model_validate({"kind": "nonsense"})

    with pytest.raises(ValidationError):
        await VoiceService(RejectsOurSchema()).route(request())


async def test_gemini_unavailable_is_voice_unavailable():
    class Down:
        async def generate_structured(self, **_):
            raise GeminiUnavailable("down")

    with pytest.raises(VoiceUnavailable):
        await VoiceService(Down()).route(request())


# Offers, offer desk and board deal intents ------------------------------------

LUMEN = OfferRef(thread_id=uuid4(), brand_name="Lumen Audio")
NOVA = OfferRef(thread_id=uuid4(), brand_name="Nova Skin")
TODAY = date(2026, 10, 14)


async def test_offer_desk_counter_merges_current_terms(gemini):
    current = TermsDraft(
        videos=3,
        price_cents=110_000,
        go_live_by=date(2026, 11, 4),
        conditions=["30-day usage rights"],
    )
    said = TermsDraft(
        price_cents=120_000,
        go_live_by=date(2026, 11, 18),  # "two more weeks"
        conditions=["30-Day usage rights", "Script approval"],
    )
    reply = RoutedIntent(kind="counter", heard="a bit more and two more weeks", terms=said)

    intent = await route(gemini, request("offer_desk", current_terms=current), reply)

    assert intent.kind == "counter"
    assert intent.terms.videos == 3
    assert intent.terms.price_cents == 120_000
    assert intent.terms.go_live_by == date(2026, 11, 18)
    assert intent.terms.conditions == ["30-day usage rights", "Script approval"]
    assert intent.creator_id is None and intent.thread_id is None


async def test_offer_desk_counter_without_current_terms_is_what_was_said(gemini):
    said = TermsDraft(price_cents=95_000, note="Happy to start next week")
    reply = RoutedIntent(kind="counter", heard="x", terms=said)

    intent = await route(gemini, request("offer_desk"), reply)

    assert intent.terms == said


async def test_counter_without_terms_is_unclear(gemini):
    intent = await route(gemini, request("offer_desk"), RoutedIntent(kind="counter", heard="x"))
    assert intent.kind == "unclear" and intent.terms is None and intent.suggestions


async def test_the_model_is_told_today_and_the_terms_on_screen(gemini):
    current = TermsDraft(videos=3, price_cents=110_000)

    gemini.queue_structured(RoutedIntent(kind="unclear", heard="x"))
    await VoiceService(gemini).route(
        request("offer_desk", "in three weeks", current_terms=current), today=TODAY
    )

    [(system, prompt, _)] = gemini.calls
    assert "Today (UTC): 2026-10-14" in prompt
    assert '"price_cents":110000' in prompt
    assert "voice never sends" in system.lower()
    assert "the user confirms on screen" in system


@pytest.mark.parametrize(
    ("kind", "reason"), [("accept", None), ("decline", "Not a fit for my audience")]
)
async def test_offer_desk_accept_and_decline_reason(gemini, kind, reason):
    reply = RoutedIntent(kind=kind, heard="x", reason=reason)

    intent = await route(gemini, request("offer_desk"), reply)

    assert intent.kind == kind and intent.reason == reason
    assert intent.terms is None and intent.creator_id is None


async def test_board_award_resolves_creator(gemini):
    reply = RoutedIntent(kind="award", heard="award Priya", creator_name="priya")

    intent = await route(gemini, request("board", visible_creators=[PRIYA, ARJUN]), reply)

    assert intent.kind == "award" and intent.creator_id == PRIYA.id


async def test_board_decline_resolves_creator_and_keeps_reason(gemini):
    reply = RoutedIntent(
        kind="decline", heard="x", creator_name="Arjun Mehta", reason="Over our budget"
    )

    intent = await route(gemini, request("board", visible_creators=[PRIYA, ARJUN]), reply)

    assert (intent.kind, intent.creator_id, intent.reason) == (
        "decline",
        ARJUN.id,
        "Over our budget",
    )


async def test_board_counter_resolves_creator_and_merges_terms(gemini):
    current = TermsDraft(videos=3, price_cents=110_000)
    reply = RoutedIntent(
        kind="counter",
        heard="counter Arjun at ninety",
        creator_name="arjun",
        terms=TermsDraft(price_cents=90_000),
    )
    req = request("board", visible_creators=[PRIYA, ARJUN], current_terms=current)

    intent = await route(gemini, req, reply)

    assert intent.kind == "counter" and intent.creator_id == ARJUN.id
    assert (intent.terms.videos, intent.terms.price_cents) == (3, 90_000)


@pytest.mark.parametrize("kind", ["counter", "award", "decline"])
async def test_board_deal_intent_for_an_unknown_creator_is_unclear(gemini, kind):
    reply = RoutedIntent(
        kind=kind, heard="x", creator_name="Zed", terms=TermsDraft(price_cents=90_000)
    )

    intent = await route(gemini, request("board", visible_creators=[PRIYA, ARJUN]), reply)

    assert intent.kind == "unclear" and intent.creator_id is None and intent.suggestions


async def test_board_counter_unknown_creator_unclear(gemini):
    reply = RoutedIntent(
        kind="counter", heard="x", creator_name="Zed", terms=TermsDraft(price_cents=1_000)
    )
    intent = await route(gemini, request("board", visible_creators=[PRIYA]), reply)
    assert intent.kind == "unclear" and intent.terms is None


async def test_board_award_without_a_name_is_unclear(gemini):
    intent = await route(gemini, request("board"), RoutedIntent(kind="award", heard="award"))
    assert intent.kind == "unclear"


async def test_offers_open_offer_by_brand(gemini):
    reply = RoutedIntent(kind="open_offer", heard="open the Lumen offer", brand_name="lumen")

    intent = await route(gemini, request("offers", visible_offers=[LUMEN, NOVA]), reply)

    assert intent.kind == "open_offer" and intent.thread_id == LUMEN.thread_id


async def test_open_offer_for_an_unknown_brand_is_unclear(gemini):
    reply = RoutedIntent(kind="open_offer", heard="x", brand_name="Acme")
    intent = await route(gemini, request("offers", visible_offers=[LUMEN, NOVA]), reply)
    assert intent.kind == "unclear" and intent.thread_id is None and intent.suggestions


async def test_open_offer_with_two_offers_from_one_brand_is_unclear(gemini):
    twin = OfferRef(thread_id=uuid4(), brand_name="Lumen Audio")
    reply = RoutedIntent(kind="open_offer", heard="x", brand_name="Lumen Audio")
    intent = await route(gemini, request("offers", visible_offers=[LUMEN, twin]), reply)
    assert intent.kind == "unclear" and intent.thread_id is None


async def test_open_offer_without_a_brand_is_unclear(gemini):
    intent = await route(gemini, request("offers"), RoutedIntent(kind="open_offer", heard="x"))
    assert intent.kind == "unclear"


@pytest.mark.parametrize(
    ("screen", "kind"),
    [
        ("offer_desk", "award"),
        ("offer_desk", "open_offer"),
        ("offer_desk", "sort"),
        ("offers", "accept"),
        ("offers", "counter"),
        ("board", "accept"),
        ("board", "open_offer"),
        ("discover", "counter"),
        ("any", "award"),
    ],
)
async def test_disallowed_intent_on_screen_is_unclear(gemini, screen, kind):
    reply = RoutedIntent(
        kind=kind,
        heard="x",
        creator_name="priya",
        brand_name="lumen",
        terms=TermsDraft(price_cents=90_000),
        sort="price",
    )
    ctx = {"visible_creators": [PRIYA], "visible_offers": [LUMEN]}

    intent = await route(gemini, request(screen, **ctx), reply)

    assert intent.kind == "unclear"
    assert intent.terms is None and intent.creator_id is None and intent.thread_id is None


@pytest.mark.parametrize("target", ["/creator/offers", "/creator/deals", "/brand/deals"])
async def test_navigate_to_the_deal_pages(gemini, target):
    reply = RoutedIntent(kind="navigate", heard="go there", navigate=target)
    intent = await route(gemini, request("any"), reply)
    assert (intent.kind, intent.navigate) == ("navigate", target)


@pytest.mark.parametrize("screen", ["offers", "offer_desk"])
async def test_new_screens_have_example_suggestions(gemini, screen):
    intent = await route(gemini, request(screen), RoutedIntent(kind="unclear", heard="mumble"))
    assert 2 <= len(intent.suggestions) <= MAX_SUGGESTIONS


@pytest.mark.parametrize("transcript", ["   ", "\t\n ", " "])
async def test_whitespace_transcript_skips_gemini(gemini, transcript):
    intent = await VoiceService(gemini).route(request("offer_desk", transcript))

    assert intent.kind == "unclear" and intent.suggestions == []
    assert gemini.calls == []

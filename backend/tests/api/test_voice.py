"""POST /voice/scribe-token and POST /voice/command against the seeded demo accounts.

Gemini and ElevenLabs are fakes; the router's rules are covered in
tests/core/test_voice_service.py, so these tests check the wiring, auth and errors.
"""

import pytest

from app.adapters.elevenlabs import ElevenLabsUnavailable
from app.adapters.gemini import GeminiInvalidOutput, GeminiUnavailable
from app.api.deps import get_elevenlabs, get_gemini
from app.schemas.packages import Addon, PackageDraft
from app.schemas.voice import RoutedIntent, RoutedSelect
from tests.fakes import FakeElevenLabs, FakeGemini
from tests.tokens import auth_header

pytestmark = pytest.mark.db

COMMAND = "/api/v1/voice/command"
SCRIBE_TOKEN = "/api/v1/voice/scribe-token"

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
VISIBLE = [
    {"id": A, "name": "Maya Chen", "handle": "mayatech"},
    {"id": B, "name": "Arjun Mehta", "handle": "arjuntech"},
]


def command(screen: str = "discover", transcript: str = "x", **context) -> dict:
    return {"screen": screen, "transcript": transcript, "context": context}


# Intent router --------------------------------------------------------------


async def test_intent_not_allowed_on_screen_becomes_unclear(brand_client, fake_gemini):
    fake_gemini.queue_structured(
        RoutedIntent(kind="package_draft", heard="x", package_draft=PackageDraft())
    )
    r = await brand_client.post(COMMAND, json=command())
    assert r.status_code == 200
    assert r.json()["kind"] == "unclear"
    assert r.json()["package_draft"] is None


async def test_search_intent_is_returned_with_its_filters(brand_client, fake_gemini):
    fake_gemini.queue_structured(
        {
            "kind": "search",
            "heard": "tech creators doing short videos under two thousand dollars",
            "search": {
                "query": "tech short videos",
                "filters": {
                    "niches": ["consumer_tech"],
                    "content_types": ["short_video"],
                    "max_price_cents": 200000,
                },
            },
        }
    )
    r = await brand_client.post(COMMAND, json=command(transcript="um tech creators ..."))
    body = r.json()
    assert body["kind"] == "search"
    assert body["search"]["filters"]["max_price_cents"] == 200000
    assert body["search"]["filters"]["niches"] == ["consumer_tech"]
    assert body["select"] is None and body["suggestions"] == []


async def test_select_names_resolved_to_ids(brand_client, fake_gemini):
    fake_gemini.queue_structured(
        RoutedIntent(
            kind="select",
            heard="select maya and arjun",
            select=RoutedSelect(creator_names=["maya", "@arjuntech", "Zed"]),
        )
    )
    r = await brand_client.post(COMMAND, json=command(visible_creators=VISIBLE))
    assert r.status_code == 200
    assert r.json()["kind"] == "select"
    assert r.json()["select"] == {"creator_ids": [A, B], "top_n": None}


async def test_package_draft_merged_with_context(creator_client, fake_gemini):
    current = PackageDraft(
        name="Launch Duo",
        base_price_cents=100_000,
        addons=[Addon(name="Extra video", price_cents=40_000, unit="video")],
    )
    fake_gemini.queue_structured(
        RoutedIntent(
            kind="package_draft",
            heard="make it twelve hundred",
            package_draft=PackageDraft(base_price_cents=120_000),
        )
    )
    r = await creator_client.post(
        COMMAND, json=command("packages", package_draft=current.model_dump())
    )
    assert r.status_code == 200
    draft = r.json()["package_draft"]
    assert r.json()["kind"] == "package_draft"
    assert draft["name"] == "Launch Duo"
    assert draft["base_price_cents"] == 120_000
    assert draft["addons"] == [{"name": "Extra video", "price_cents": 40_000, "unit": "video"}]


async def test_negative_cents_from_model_rejected_as_unclear(brand_client, fake_gemini):
    fake_gemini.queue_structured(
        {
            "kind": "search",
            "heard": "under minus five",
            "search": {"filters": {"max_price_cents": -5}},
        }
    )
    r = await brand_client.post(COMMAND, json=command(transcript="creators under minus five"))
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "unclear"
    assert body["heard"] == "creators under minus five"
    assert 2 <= len(body["suggestions"]) <= 3
    assert body["search"] is None


async def test_model_prompt_carries_the_screen_context(brand_client, fake_gemini: FakeGemini):
    fake_gemini.queue_structured(RoutedIntent(kind="unclear", heard="x"))
    await brand_client.post(COMMAND, json=command("review", "pick maya", visible_creators=VISIBLE))
    [(_, prompt, schema)] = fake_gemini.calls
    assert schema is RoutedIntent
    assert "Screen: review" in prompt and "Maya Chen (@mayatech)" in prompt
    assert "pick maya" in prompt


async def test_unusable_model_output_is_unclear(brand_client, app):
    class Garbled:
        async def generate_structured(self, **_):
            raise GeminiInvalidOutput("no JSON")

    app.dependency_overrides[get_gemini] = lambda: Garbled()
    r = await brand_client.post(COMMAND, json=command(transcript="blah blah"))
    assert r.status_code == 200
    assert r.json()["kind"] == "unclear" and r.json()["heard"] == "blah blah"


async def test_model_unavailable_is_503_voice_unavailable(brand_client, app):
    class Down:
        async def generate_structured(self, **_):
            raise GeminiUnavailable("down")

    app.dependency_overrides[get_gemini] = lambda: Down()
    r = await brand_client.post(COMMAND, json=command())
    assert r.status_code == 503
    assert r.json() == {"detail": "voice_unavailable"}


@pytest.mark.parametrize(
    "body",
    [
        {"screen": "discover", "transcript": "", "context": {}},
        {"screen": "discover", "transcript": "x" * 501, "context": {}},
        {"screen": "nowhere", "transcript": "x", "context": {}},
        {"screen": "discover", "transcript": "x"},
        {
            "screen": "discover",
            "transcript": "x",
            "context": {"visible_creators": [{"id": "not-a-uuid", "name": "n", "handle": "h"}]},
        },
    ],
)
async def test_invalid_command_is_422_without_asking_the_model(brand_client, fake_gemini, body):
    r = await brand_client.post(COMMAND, json=body)
    assert r.status_code == 422
    assert fake_gemini.calls == []


# Scribe token ---------------------------------------------------------------


async def test_scribe_token_for_a_brand(brand_client, fake_elevenlabs: FakeElevenLabs):
    r = await brand_client.post(SCRIBE_TOKEN)
    assert r.status_code == 200
    assert r.json() == {
        "token": "fake-scribe-token",
        "expires_at": "2026-10-09T12:15:00+00:00",
    }
    assert fake_elevenlabs.mint_calls == 1


async def test_scribe_token_for_a_creator(creator_client):
    r = await creator_client.post(SCRIBE_TOKEN)
    assert r.status_code == 200
    assert r.json()["token"] == "fake-scribe-token"


async def test_scribe_token_failure_is_503_voice_unavailable(brand_client, app):
    app.dependency_overrides[get_elevenlabs] = lambda: FakeElevenLabs(
        failure=ElevenLabsUnavailable("down")
    )
    r = await brand_client.post(SCRIBE_TOKEN)
    assert r.status_code == 503
    assert r.json() == {"detail": "voice_unavailable"}


# Auth -----------------------------------------------------------------------


@pytest.mark.parametrize("path", [SCRIBE_TOKEN, COMMAND])
async def test_voice_requires_auth(client, path):
    r = await client.post(path, json=command())
    assert r.status_code == 401
    assert r.json() == {"detail": "not_authenticated"}


@pytest.mark.parametrize("path", [SCRIBE_TOKEN, COMMAND])
async def test_voice_before_onboarding_is_409(
    client, fake_jwks, fake_gemini, fake_elevenlabs, auth_user, path
):
    r = await client.post(path, json=command(), headers=auth_header(auth_user))
    assert r.status_code == 409
    assert r.json() == {"detail": "onboarding_required"}
    assert fake_gemini.calls == [] and fake_elevenlabs.mint_calls == 0

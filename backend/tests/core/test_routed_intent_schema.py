"""Every schema we hand Gemini as a response schema, built offline by the real SDK (respx).

A keyword the SDK's schema type does not know (pydantic's PositiveInt writes
`exclusiveMinimum`) makes it raise before sending anything, which a service would then
report as an unusable reply for every request.
"""

import json
from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from app.adapters.gemini import GeminiClient
from app.config import Settings
from app.modules.negotiation.prompts import StructuredCall
from app.schemas.negotiation import TermsDraft
from app.schemas.packages import ExtractedDraft
from app.schemas.voice import RoutedIntent

GENERATE_URL = r".*/models/gemini-3\.8-flash:generateContent$"

ROUTED_INTENT_REPLY = {
    "kind": "search",
    "heard": "tech creators under two grand",
    "search": {"filters": {"niches": ["consumer_tech"], "max_price_cents": 200000, "region": "IN"}},
}
OPEN_THREAD_REPLY = {
    "kind": "open_thread",
    "heard": "open Priya's thread",
    "open_thread_name": "priya",
}
COUNTER_REPLY = {
    "kind": "counter",
    "heard": "make it twelve hundred and two more weeks",
    "creator_name": "priya",
    "terms": {
        "videos": 3,
        "price_cents": 120000,
        "go_live_by": "2026-11-18",
        "conditions": ["30-day usage rights"],
        "note": "Happy to start next week",
    },
}
DECLINE_REPLY = {
    "kind": "decline",
    "heard": "decline, it is not a fit",
    "brand_name": "lumen",
    "reason": "Not a fit",
}
SORT_REPLY = {"kind": "sort", "heard": "sort by price", "sort": "price"}
EXTRACTED_DRAFT_REPLY = {
    "heard": "two videos for a thousand with a thumbnail pack for fifty",
    "draft": {
        "volume_count": 2,
        "base_price_cents": 100000,
        "addons": [{"name": "Extra video", "price_cents": 40000, "unit": "video"}],
        "extras": [{"name": "Thumbnail pack", "price_cents": 5000}],
    },
}
STRUCTURED_CALL_REPLY = {
    "terms": {
        "videos": 1,
        "price_cents": 100000,
        "stance": "counter",
        "source": "call",
        "confidence": 0.85,
    },
    "summary": "Creator countered at $1,000 for one video.",
}


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, gemini_api_key="test-key", gemini_text_model="gemini-3.8-flash")


@pytest.mark.parametrize(
    ("schema", "reply"),
    [
        (RoutedIntent, ROUTED_INTENT_REPLY),
        (RoutedIntent, OPEN_THREAD_REPLY),
        (RoutedIntent, SORT_REPLY),
        (RoutedIntent, COUNTER_REPLY),
        (RoutedIntent, DECLINE_REPLY),
        (ExtractedDraft, EXTRACTED_DRAFT_REPLY),
        (StructuredCall, STRUCTURED_CALL_REPLY),
    ],
)
async def test_the_sdk_accepts_our_response_schemas(settings, respx_mock, schema, reply):
    candidate = {"content": {"role": "model", "parts": [{"text": json.dumps(reply)}]}}
    route = respx_mock.post(url__regex=GENERATE_URL).mock(
        return_value=httpx.Response(200, json={"candidates": [candidate]})
    )

    parsed = await GeminiClient(settings).generate_structured(system="s", prompt="p", schema=schema)

    assert parsed.model_dump(exclude_defaults=True) == schema.model_validate(reply).model_dump(
        exclude_defaults=True
    )
    sent = route.calls.last.request.content.decode()
    assert "responseSchema" in sent and "exclusiveMinimum" not in sent


def test_routed_intent_schema_accepts_terms():
    routed = RoutedIntent.model_validate(COUNTER_REPLY)

    assert routed.terms == TermsDraft(
        videos=3,
        price_cents=120_000,
        go_live_by=date(2026, 11, 18),
        conditions=["30-day usage rights"],
        note="Happy to start next week",
    )
    assert routed.creator_name == "priya"
    assert RoutedIntent.model_validate(DECLINE_REPLY).reason == "Not a fit"
    with pytest.raises(ValidationError):
        RoutedIntent.model_validate({"kind": "counter", "heard": "x", "terms": {"price_cents": 5}})

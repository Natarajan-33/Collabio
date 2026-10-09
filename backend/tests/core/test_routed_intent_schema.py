"""Every schema we hand Gemini as a response schema, built offline by the real SDK (respx).

A keyword the SDK's schema type does not know (pydantic's PositiveInt writes
`exclusiveMinimum`) makes it raise before sending anything, which a service would then
report as an unusable reply for every request.
"""

import json

import httpx
import pytest

from app.adapters.gemini import GeminiClient
from app.config import Settings
from app.schemas.packages import ExtractedDraft
from app.schemas.voice import RoutedIntent

GENERATE_URL = r".*/models/gemini-3\.8-flash:generateContent$"

ROUTED_INTENT_REPLY = {
    "kind": "search",
    "heard": "tech creators under two grand",
    "search": {"filters": {"niches": ["consumer_tech"], "max_price_cents": 200000}},
}
EXTRACTED_DRAFT_REPLY = {
    "heard": "two videos for a thousand with a thumbnail pack for fifty",
    "draft": {
        "volume_count": 2,
        "base_price_cents": 100000,
        "addons": [{"name": "Extra video", "price_cents": 40000, "unit": "video"}],
        "extras": [{"name": "Thumbnail pack", "price_cents": 5000}],
    },
}


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, gemini_api_key="test-key", gemini_text_model="gemini-3.8-flash")


@pytest.mark.parametrize(
    ("schema", "reply"),
    [(RoutedIntent, ROUTED_INTENT_REPLY), (ExtractedDraft, EXTRACTED_DRAFT_REPLY)],
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

"""RoutedIntent as Gemini's response schema, built offline by the real SDK (respx)."""

import json

import httpx
import pytest

from app.adapters.gemini import GeminiClient
from app.config import Settings
from app.schemas.voice import RoutedIntent

GENERATE_URL = r".*/models/gemini-3\.8-flash:generateContent$"
REPLY = {
    "kind": "search",
    "heard": "tech creators under two grand",
    "search": {"filters": {"niches": ["consumer_tech"], "max_price_cents": 200000}},
}


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, gemini_api_key="test-key", gemini_text_model="gemini-3.8-flash")


async def test_the_sdk_accepts_routed_intent_as_a_response_schema(settings, respx_mock):
    # A keyword the SDK's schema type does not know (pydantic's PositiveInt writes
    # `exclusiveMinimum`) makes it raise before sending anything, which the router would
    # then report as `unclear` for every command.
    candidate = {"content": {"role": "model", "parts": [{"text": json.dumps(REPLY)}]}}
    route = respx_mock.post(url__regex=GENERATE_URL).mock(
        return_value=httpx.Response(200, json={"candidates": [candidate]})
    )

    routed = await GeminiClient(settings).generate_structured(
        system="s", prompt="p", schema=RoutedIntent
    )

    assert routed.search.filters.max_price_cents == 200000
    sent = route.calls.last.request.content.decode()
    assert "responseSchema" in sent and "exclusiveMinimum" not in sent

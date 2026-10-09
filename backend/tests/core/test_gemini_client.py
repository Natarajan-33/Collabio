"""GeminiClient against a mocked Gemini REST API (respx): request shape, batching, errors."""

import json

import httpx
import pytest
from google.genai import errors
from pydantic import BaseModel
from tenacity import wait_none

from app.adapters import gemini
from app.adapters.gemini import (
    GeminiClient,
    GeminiInvalidOutput,
    GeminiUnavailable,
    format_document,
)
from app.config import Settings

EMBED_URL = r".*/models/gemini-embedding-2:batchEmbedContents$"
GENERATE_URL = r".*/models/gemini-3\.8-flash:generateContent$"


class Total(BaseModel):
    total: int


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key="test-key",
        gemini_text_model="gemini-3.8-flash",
        gemini_embed_model="gemini-embedding-2",
    )


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini, "RETRY_WAIT", wait_none())


class EmbedEcho:
    """Answers batchEmbedContents with one vector per request, numbered in arrival order."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        embeddings = []
        for item in json.loads(request.content)["requests"]:
            [part] = item["content"]["parts"]
            self.texts.append(part["text"])
            embeddings.append({"values": [float(len(self.texts) - 1)] + [0.0] * 767})
        return httpx.Response(200, json={"embeddings": embeddings})


def requests_in(call) -> list[dict]:
    return json.loads(call.request.content)["requests"]


def api_error(status: int) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": "nope"}})


def model_reply(text: str) -> httpx.Response:
    candidate = {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
    return httpx.Response(200, json={"candidates": [candidate]})


# Embeddings -----------------------------------------------------------------


async def test_embed_documents_sends_each_document_as_its_own_content(settings, respx_mock):
    route = respx_mock.post(url__regex=EMBED_URL).mock(side_effect=EmbedEcho())

    vecs = await GeminiClient(settings).embed_documents([("Maya", "tech"), ("", "beauty")])

    [call] = route.calls
    sent = requests_in(call)
    assert [item["content"]["parts"] for item in sent] == [
        [{"text": "title: Maya | text: tech"}],
        [{"text": "title: none | text: beauty"}],
    ]
    assert all(item["outputDimensionality"] == 768 for item in sent)
    assert [v[0] for v in vecs] == [0.0, 1.0]
    assert all(len(v) == 768 for v in vecs)


async def test_embed_documents_batches_fifty_per_request_in_order(settings, respx_mock):
    echo = EmbedEcho()
    route = respx_mock.post(url__regex=EMBED_URL).mock(side_effect=echo)
    docs = [("", f"doc {i}") for i in range(120)]

    vecs = await GeminiClient(settings).embed_documents(docs)

    assert [len(requests_in(call)) for call in route.calls] == [50, 50, 20]
    assert echo.texts == [format_document(title, text) for title, text in docs]
    assert [v[0] for v in vecs] == [float(i) for i in range(120)]


async def test_embed_documents_with_no_documents_makes_no_request(settings, respx_mock):
    assert await GeminiClient(settings).embed_documents([]) == []


async def test_embed_query_uses_the_search_query_format(settings, respx_mock):
    route = respx_mock.post(url__regex=EMBED_URL).mock(side_effect=EmbedEcho())

    vec = await GeminiClient(settings).embed_query("tech creators")

    [item] = requests_in(route.calls.last)
    assert item["content"]["parts"] == [{"text": "task: search result | query: tech creators"}]
    assert item["outputDimensionality"] == 768
    assert len(vec) == 768


async def test_fewer_embeddings_than_documents_is_invalid_output(settings, respx_mock):
    one_vector = {"embeddings": [{"values": [0.0] * 768}]}
    respx_mock.post(url__regex=EMBED_URL).mock(return_value=httpx.Response(200, json=one_vector))

    with pytest.raises(GeminiInvalidOutput):
        await GeminiClient(settings).embed_documents([("A", "tech"), ("B", "beauty")])


async def test_wrong_embedding_width_is_invalid_output(settings, respx_mock):
    full_width = {"embeddings": [{"values": [0.0] * 3072}]}
    respx_mock.post(url__regex=EMBED_URL).mock(return_value=httpx.Response(200, json=full_width))

    with pytest.raises(GeminiInvalidOutput):
        await GeminiClient(settings).embed_query("tech creators")


# Retries --------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_transient_status_is_retried(settings, respx_mock, status):
    echo = EmbedEcho()
    route = respx_mock.post(url__regex=EMBED_URL).mock(
        side_effect=[api_error(status), api_error(status), echo]
    )

    vec = await GeminiClient(settings).embed_query("tech creators")

    assert route.call_count == 3
    assert len(vec) == 768


async def test_network_error_is_retried(settings, respx_mock):
    route = respx_mock.post(url__regex=EMBED_URL).mock(
        side_effect=[httpx.ConnectError("connection refused"), EmbedEcho()]
    )

    await GeminiClient(settings).embed_query("tech creators")

    assert route.call_count == 2


async def test_unavailable_after_three_attempts(settings, respx_mock):
    route = respx_mock.post(url__regex=EMBED_URL).mock(return_value=api_error(503))

    with pytest.raises(GeminiUnavailable) as caught:
        await GeminiClient(settings).embed_query("tech creators")

    assert route.call_count == 3
    assert isinstance(caught.value.__cause__, errors.ServerError)


async def test_client_error_is_not_retried(settings, respx_mock):
    route = respx_mock.post(url__regex=EMBED_URL).mock(return_value=api_error(400))

    with pytest.raises(GeminiUnavailable) as caught:
        await GeminiClient(settings).embed_query("tech creators")

    assert route.call_count == 1
    assert isinstance(caught.value.__cause__, errors.ClientError)


# Structured output ----------------------------------------------------------


async def test_generate_structured_returns_the_parsed_model(settings, respx_mock):
    route = respx_mock.post(url__regex=GENERATE_URL).mock(return_value=model_reply('{"total": 42}'))

    result = await GeminiClient(settings).generate_structured(
        system="You add numbers.", prompt="Add 17 and 25.", schema=Total
    )

    assert result == Total(total=42)
    body = json.loads(route.calls.last.request.content)
    assert body["systemInstruction"]["parts"] == [{"text": "You add numbers."}]
    assert body["contents"][0]["parts"] == [{"text": "Add 17 and 25."}]
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["properties"]["total"]["type"] == "INTEGER"
    assert list(config["thinkingConfig"].values()) == ["LOW"]


@pytest.mark.parametrize("reply", ['{"total": "lots"}', '{"sum": 42}', "not json"])
async def test_output_that_breaks_the_schema_is_invalid_and_not_retried(
    settings, respx_mock, reply
):
    route = respx_mock.post(url__regex=GENERATE_URL).mock(return_value=model_reply(reply))

    with pytest.raises(GeminiInvalidOutput):
        await GeminiClient(settings).generate_structured(system="s", prompt="p", schema=Total)

    assert route.call_count == 1


async def test_reply_without_text_is_invalid_output(settings, respx_mock):
    blocked = {"candidates": [{"finishReason": "SAFETY"}]}
    respx_mock.post(url__regex=GENERATE_URL).mock(return_value=httpx.Response(200, json=blocked))

    with pytest.raises(GeminiInvalidOutput):
        await GeminiClient(settings).generate_structured(system="s", prompt="p", schema=Total)


async def test_generate_structured_retries_then_reports_unavailable(settings, respx_mock):
    route = respx_mock.post(url__regex=GENERATE_URL).mock(return_value=api_error(429))

    with pytest.raises(GeminiUnavailable):
        await GeminiClient(settings).generate_structured(system="s", prompt="p", schema=Total)

    assert route.call_count == 3

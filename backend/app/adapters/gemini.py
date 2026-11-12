"""Gemini adapter: text embeddings for creator search and structured (JSON) output.

Services depend on `GeminiPort`; `GeminiClient` implements it over the google-genai SDK
and tests substitute `tests.fakes.FakeGemini`.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import Settings

EMBED_DIMENSIONS = 768
EMBED_BATCH_SIZE = 50

REQUEST_TIMEOUT_MS = 30_000
RETRY_ATTEMPTS = 3
RETRY_WAIT = wait_exponential_jitter(initial=0.5, max=4.0)
# Rate limiting, request timeout and server-side failures; anything else fails at once.
TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def format_document(title: str, text: str) -> str:
    """gemini-embedding-2 retrieval document format; `title: none` when there is no title."""
    return f"title: {title or 'none'} | text: {text}"


def format_query(query: str) -> str:
    """gemini-embedding-2 search-query format, asymmetric to `format_document`."""
    return f"task: search result | query: {query}"


class GeminiUnavailable(Exception):
    """Gemini did not answer: a network or API error, after retrying transient ones."""


class GeminiInvalidOutput(Exception):
    """Gemini answered, but the output is missing or does not fit the requested shape."""


class GeminiPort(Protocol):
    async def embed_documents(self, docs: list[tuple[str, str]]) -> list[list[float]]:
        """One vector per `(title, text)` document, in input order."""
        ...

    async def embed_query(self, query: str) -> list[float]: ...

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, schema: type[T]
    ) -> T: ...


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in TRANSIENT_STATUS_CODES
    return isinstance(exc, httpx.TimeoutException | httpx.NetworkError | httpx.RemoteProtocolError)


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_MS,
                # Pin httpx: google-genai switches to aiohttp whenever it is importable (the
                # Render SDK brings it in), which would bypass `_is_transient` and respx.
                httpx_async_client=httpx.AsyncClient(timeout=REQUEST_TIMEOUT_MS / 1000),
            ),
        )
        self._text_model = settings.gemini_text_model
        self._embed_model = settings.gemini_embed_model

    async def embed_documents(self, docs: list[tuple[str, str]]) -> list[list[float]]:
        texts = [format_document(title, text) for title, text in docs]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            vectors.extend(await self._embed(texts[start : start + EMBED_BATCH_SIZE]))
        return vectors

    async def embed_query(self, query: str) -> list[float]:
        [vector] = await self._embed([format_query(query)])
        return vector

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, schema: type[T]
    ) -> T:
        response = await self._call(
            self._client.aio.models.generate_content,
            model=self._text_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        # The SDK validates the JSON against `schema` and leaves `parsed` as None when
        # the reply is empty, blocked, not JSON, or fails validation.
        parsed = response.parsed
        if not isinstance(parsed, schema):
            raise GeminiInvalidOutput(f"{self._text_model} reply does not fit {schema.__name__}")
        return parsed

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        # Each text gets its own Content: gemini-embedding-2 merges the parts of a single
        # Content (which a bare list of strings becomes) into ONE aggregated embedding.
        response = await self._call(
            self._client.aio.models.embed_content,
            model=self._embed_model,
            contents=[types.Content(parts=[types.Part(text=text)]) for text in texts],
            config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMENSIONS),
        )
        vectors = [list(embedding.values or []) for embedding in response.embeddings or []]
        if len(vectors) != len(texts) or any(len(v) != EMBED_DIMENSIONS for v in vectors):
            widths = sorted({len(v) for v in vectors})
            raise GeminiInvalidOutput(
                f"{self._embed_model} returned {len(vectors)} embeddings of width {widths}"
                f" for {len(texts)} texts; expected one {EMBED_DIMENSIONS}-wide vector each"
            )
        return vectors

    async def _call[R](self, method: Callable[..., Awaitable[R]], **kwargs: Any) -> R:
        """Awaits an SDK method, retrying transient failures; GeminiUnavailable if it never
        succeeds. Invalid output is not an exception here, so it is never retried."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(RETRY_ATTEMPTS),
            wait=RETRY_WAIT,
            retry=retry_if_exception(_is_transient),
            reraise=True,
        )
        try:
            return await retrying(method, **kwargs)
        except (errors.APIError, httpx.TransportError) as exc:
            raise GeminiUnavailable(f"Gemini request failed: {exc}") from exc

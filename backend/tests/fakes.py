"""Deterministic stand-ins for the adapters' ports, for tests that must not call real APIs."""

import hashlib
import math
from collections import deque
from typing import Any

from pydantic import BaseModel, ValidationError

from app.adapters.gemini import (
    EMBED_DIMENSIONS,
    GeminiInvalidOutput,
    format_document,
    format_query,
)
from app.schemas.voice import ScribeToken


def fake_embedding(text: str) -> list[float]:
    """A unit vector derived from sha256(text): equal texts embed equally, others differ."""
    digest = b"".join(
        hashlib.sha256(f"{block}|{text}".encode()).digest()
        for block in range(EMBED_DIMENSIONS // 32)  # 32 bytes per digest, one byte per float
    )
    values = [byte - 127.5 for byte in digest]  # never 0, so the norm is never 0
    norm = math.sqrt(math.fsum(v * v for v in values))
    return [v / norm for v in values]


class FakeGemini:
    """GeminiPort without the network.

    Embeddings hash the same formatted text the real client sends. `embed_calls`
    counts embedding requests (one per `embed_documents` or `embed_query` call);
    set `embed_failure` to make every embedding request raise it (after being counted).
    `generate_structured` returns objects queued with `queue_structured` in FIFO
    order and records each `(system, prompt, schema)` in `calls`.
    """

    def __init__(self) -> None:
        self.embed_calls = 0
        self.embed_failure: Exception | None = None
        self.calls: list[tuple[str, str, type[BaseModel]]] = []
        self._queued: deque[BaseModel | dict[str, Any]] = deque()

    async def embed_documents(self, docs: list[tuple[str, str]]) -> list[list[float]]:
        self._count_embed_call()
        return [fake_embedding(format_document(title, text)) for title, text in docs]

    async def embed_query(self, query: str) -> list[float]:
        self._count_embed_call()
        return fake_embedding(format_query(query))

    def _count_embed_call(self) -> None:
        self.embed_calls += 1
        if self.embed_failure is not None:
            raise self.embed_failure

    def queue_structured(self, obj: BaseModel | dict[str, Any]) -> None:
        """Queue the next model reply: a model instance, or a raw dict validated against
        the caller's schema when it is returned. Schema-breaking data raises GeminiInvalidOutput,
        as GeminiClient does for a reply that does not fit the schema."""
        self._queued.append(obj)

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, schema: type[T]
    ) -> T:
        self.calls.append((system, prompt, schema))
        if not self._queued:
            raise AssertionError("FakeGemini.generate_structured called with nothing queued")
        obj = self._queued.popleft()
        if isinstance(obj, dict):
            try:
                return schema.model_validate(obj)
            except ValidationError as exc:
                raise GeminiInvalidOutput(f"queued reply does not fit {schema.__name__}") from exc
        if not isinstance(obj, schema):
            raise TypeError(f"queued a {type(obj).__name__}; the caller wants {schema.__name__}")
        return obj


class FakeElevenLabs:
    """ElevenLabsPort without the network: hands out `token`, or raises `failure` if given."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.mint_calls = 0
        self._failure = failure

    async def mint_scribe_token(self) -> ScribeToken:
        self.mint_calls += 1
        if self._failure is not None:
            raise self._failure
        return ScribeToken(token="fake-scribe-token", expires_at="2026-10-09T12:15:00+00:00")

"""Deterministic stand-ins for the adapters' ports, for tests that must not call real APIs."""

import hashlib
import math
from collections import deque
from typing import Any

from pydantic import BaseModel

from app.adapters.gemini import EMBED_DIMENSIONS, format_document, format_query


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
    counts embedding requests (one per `embed_documents` or `embed_query` call).
    `generate_structured` returns objects queued with `queue_structured` in FIFO
    order and records each `(system, prompt, schema)` in `calls`.
    """

    def __init__(self) -> None:
        self.embed_calls = 0
        self.calls: list[tuple[str, str, type[BaseModel]]] = []
        self._queued: deque[BaseModel | dict[str, Any]] = deque()

    async def embed_documents(self, docs: list[tuple[str, str]]) -> list[list[float]]:
        self.embed_calls += 1
        return [fake_embedding(format_document(title, text)) for title, text in docs]

    async def embed_query(self, query: str) -> list[float]:
        self.embed_calls += 1
        return fake_embedding(format_query(query))

    def queue_structured(self, obj: BaseModel | dict[str, Any]) -> None:
        """Queue the next model reply: a model instance, or a raw dict validated against
        the caller's schema when it is returned. Schema-breaking data raises pydantic's
        ValidationError (GeminiClient raises GeminiInvalidOutput for such a reply)."""
        self._queued.append(obj)

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, schema: type[T]
    ) -> T:
        self.calls.append((system, prompt, schema))
        if not self._queued:
            raise AssertionError("FakeGemini.generate_structured called with nothing queued")
        obj = self._queued.popleft()
        if isinstance(obj, dict):
            return schema.model_validate(obj)
        if not isinstance(obj, schema):
            raise TypeError(f"queued a {type(obj).__name__}; the caller wants {schema.__name__}")
        return obj

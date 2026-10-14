"""Deterministic stand-ins for the adapters' ports, for tests that must not call real APIs."""

import hashlib
import math
import uuid
from collections import deque
from typing import Any

from pydantic import BaseModel, ValidationError

from app.adapters.elevenlabs import (
    ConversationSnapshot,
    ElevenLabsUnavailable,
)
from app.adapters.email import EmailRejected, OutboundEmail, ReceivedEmail
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


# The tests share one hosted database, and committed rows (a crashed run's, or an earlier
# test's) keep the ids a fake handed out. Every process, and every fake, mints ids with its own
# random prefix, so a leftover can never collide with a new one.
RUN = uuid.uuid4().hex[:8]


def conv_id(n: int) -> str:
    """A conversation id of this process's own, for tests that store one without a fake."""
    return f"conv_{RUN}_{n}"


class FakeElevenLabs:
    """ElevenLabsPort without the network.

    `mint_scribe_token` hands out a fixed token, or raises `failure` if given.
    `mint_conversation_token` records the agent id in `conversation_tokens`.
    `place_call` records its kwargs in `calls`, raises `call_failure` if set, and
    returns `conv_<run>_1`, `conv_<run>_2`, ... (`conv_id(n)` names the n-th; a failed
    placement uses up no id). The prefix is random per fake.
    `get_conversation` serves `snapshots` by id; a missing id raises `ElevenLabsUnavailable`.
    """

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.mint_calls = 0
        self._failure = failure
        self.conversation_tokens: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.call_failure: Exception | None = None
        self.snapshots: dict[str, ConversationSnapshot] = {}
        self._placed = 0
        self._run = uuid.uuid4().hex[:8]

    async def mint_scribe_token(self) -> ScribeToken:
        self.mint_calls += 1
        if self._failure is not None:
            raise self._failure
        return ScribeToken(token="fake-scribe-token", expires_at="2026-10-09T12:15:00+00:00")

    async def mint_conversation_token(self, agent_id: str) -> str:
        self.conversation_tokens.append(agent_id)
        return f"fake-conversation-token-{len(self.conversation_tokens)}"

    async def place_call(
        self,
        *,
        agent_id: str,
        phone_number_id: str,
        to_number: str,
        dynamic_variables: dict[str, str],
    ) -> str:
        self.calls.append(
            {
                "agent_id": agent_id,
                "phone_number_id": phone_number_id,
                "to_number": to_number,
                "dynamic_variables": dynamic_variables,
            }
        )
        if self.call_failure is not None:
            raise self.call_failure
        self._placed += 1
        return self.conv_id(self._placed)

    def conv_id(self, n: int) -> str:
        return f"conv_{self._run}_{n}"

    async def get_conversation(self, conversation_id: str) -> ConversationSnapshot:
        try:
            return self.snapshots[conversation_id]
        except KeyError:
            raise ElevenLabsUnavailable(f"no snapshot for {conversation_id}") from None


class FakeEmail:
    """EmailPort without the network; dedupes by idempotency key, like Resend.

    `sent` holds `(email, idempotency_key)` per distinct key. `failures` maps a
    recipient address to the exception its send raises (nothing is recorded).
    With `crash_after_send` the send is recorded, then `RuntimeError("crash")` is raised,
    as when the process dies between Resend accepting the mail and the app noting it.
    `received` serves inbound bodies by email id (a missing id is `EmailRejected`, like a 404);
    set `received_failure` to make every `get_received` raise it.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[OutboundEmail, str]] = []
        self.failures: dict[str, Exception] = {}
        self.crash_after_send = False
        self.received: dict[str, ReceivedEmail] = {}
        self.received_failure: Exception | None = None
        self._ids: dict[str, str] = {}
        self._run = uuid.uuid4().hex[:8]

    async def send(self, email: OutboundEmail, *, idempotency_key: str) -> str:
        if email.to in self.failures:
            raise self.failures[email.to]
        sent_id = self._ids.get(idempotency_key)
        if sent_id is None:
            sent_id = self.email_id(len(self._ids) + 1)
            self._ids[idempotency_key] = sent_id
            self.sent.append((email, idempotency_key))
        if self.crash_after_send:
            raise RuntimeError("crash")
        return sent_id

    async def get_received(self, email_id: str) -> ReceivedEmail:
        if self.received_failure is not None:
            raise self.received_failure
        try:
            return self.received[email_id]
        except KeyError:
            raise EmailRejected(f"no received email {email_id}") from None

    def email_id(self, n: int) -> str:
        """The id this fake gives its n-th distinct send (random prefix per fake)."""
        return f"email_{self._run}_{n}"

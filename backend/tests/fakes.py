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


class FakePayPal:
    """In-memory PayPal: orders approve themselves, captures complete, payouts start PENDING.

    Set `payout_error` to a `PayPalError` to make the next `create_payout` raise it, and
    `payout_status` to the item status `get_payout_batch` reports."""

    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.payouts: list[dict] = []
        self.refunds: list[dict] = []
        self.captures = 0
        self.payout_error: Exception | None = None
        self.payout_status = "SUCCESS"
        self.webhook_ok = True

    async def create_order(
        self, *, amount_cents, custom_id, invoice_id, description, return_url, cancel_url
    ):
        order_id = f"ORDER{len(self.orders) + 1}"
        self.orders[order_id] = {"amount_cents": amount_cents, "custom_id": custom_id}
        return {
            "id": order_id,
            "status": "PAYER_ACTION_REQUIRED",
            "approve_url": f"https://sandbox.paypal.test/checkoutnow?token={order_id}",
        }

    async def get_order(self, order_id):
        order = self.orders.get(order_id, {})
        return {"id": order_id, "status": order.get("status", "PAYER_ACTION_REQUIRED")}

    async def capture_order(self, order_id):
        self.captures += 1
        order = self.orders[order_id]
        order["status"] = "COMPLETED"
        return {
            "status": "COMPLETED",
            "capture_status": "COMPLETED",
            "capture_id": f"CAP-{order_id}",
            "amount_cents": order["amount_cents"],
            "custom_id": order["custom_id"],
        }

    async def refund_capture(self, capture_id, amount_cents, note, *, request_id=None):
        self.refunds.append({"capture_id": capture_id, "amount_cents": amount_cents})
        return {"id": f"REF{len(self.refunds)}", "status": "COMPLETED"}

    async def create_payout(self, sender_batch_id, receiver_email, amount_cents, note):
        if self.payout_error is not None:
            error, self.payout_error = self.payout_error, None
            raise error
        self.payouts.append(
            {
                "sender_batch_id": sender_batch_id,
                "receiver_email": receiver_email,
                "amount_cents": amount_cents,
            }
        )
        n = len(self.payouts)
        return {"batch_id": f"BATCH{n}", "item_id": f"ITEM{n}", "batch_status": "PENDING"}

    async def get_payout_batch(self, batch_id):
        n = batch_id.removeprefix("BATCH")
        return {
            "batch_status": "SUCCESS",
            "item_id": f"ITEM{n}",
            "item_status": self.payout_status,
            "errors": None,
        }

    async def verify_webhook(self, headers, body, webhook_id):
        return self.webhook_ok


class FakeClaude:
    """Scripted Claude: each `create` returns the next message dict from `script` and
    records the request. A script entry that is an Exception is raised instead."""

    def __init__(self, script: list | None = None) -> None:
        self.script = list(script or [])
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.script:
            raise AssertionError("FakeClaude script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def claude_text(payload: dict | str) -> dict:
    """A Claude message whose only block is JSON text (structured output)."""
    import json

    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}


def claude_tool_use(name: str, tool_input: dict, tool_id: str = "toolu_1") -> dict:
    return {
        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}],
        "stop_reason": "tool_use",
    }


class FakeStorage:
    """In-memory Supabase Storage for proof screenshots."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        self.objects[path] = (data, content_type)

    async def download(self, path: str) -> bytes:
        return self.objects[path][0]

    async def signed_url(self, path: str, ttl_s: int = 3600) -> str:
        return f"https://storage.test/{path}?ttl={ttl_s}"

"""Email adapter: transactional mail over the Resend REST API.

Services depend on `EmailPort`; `ResendClient` implements it over `httpx` (Resend's
Python SDK is synchronous) and tests substitute `tests.fakes.FakeEmail`.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import Settings

RESEND_EMAILS_URL = "https://api.resend.com/emails"
RESEND_RECEIVED_URL = "https://api.resend.com/emails/receiving"
REQUEST_TIMEOUT_SECONDS = 15.0
RETRY_ATTEMPTS = 3
RETRY_WAIT = wait_exponential_jitter(initial=0.5, max=4.0)
RATE_LIMITED = 429
SERVER_ERROR = 500  # 5xx and up is transient; every other 4xx fails at once


class OutboundEmail(BaseModel):
    to: str
    sender: str
    reply_to: str | None
    subject: str
    html: str
    text: str
    headers: dict[str, str] = Field(default_factory=dict)


class ReceivedEmail(BaseModel):
    """An inbound email as Resend's receiving API returns it (the webhook carries no body)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_: str = Field(alias="from")
    to: list[str]
    received_for: list[str] = []
    subject: str = ""
    text: str | None = None
    html: str | None = None
    attachments: list[dict] = []


class EmailRejected(Exception):
    """Resend refused the email (a 4xx that retrying cannot fix); `str(exc)` is its message."""


class EmailUnavailable(Exception):
    """Resend did not accept the email: a network or server error, after retrying."""


class EmailPort(Protocol):
    async def send(self, email: OutboundEmail, *, idempotency_key: str) -> str:
        """Send `email`; the Resend email id. The same key never sends twice."""
        ...

    async def get_received(self, email_id: str) -> ReceivedEmail:
        """The inbound email `email_id`. `EmailRejected` when Resend has no such email,
        `EmailUnavailable` on a network or server error after retrying."""
        ...


class _TransientStatus(Exception):
    """A response worth retrying (429, 5xx)."""


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, _TransientStatus | httpx.TransportError)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    message = body.get("message") if isinstance(body, dict) else None
    return message if isinstance(message, str) and message else response.text[:200]


class ResendClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.resend_api_key:
            raise ValueError("RESEND_API_KEY is not set")
        self._http = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )

    async def send(self, email: OutboundEmail, *, idempotency_key: str) -> str:
        payload: dict[str, Any] = {
            "from": email.sender,
            "to": [email.to],
            "subject": email.subject,
            "html": email.html,
            "text": email.text,
            "headers": email.headers,
        }
        if email.reply_to is not None:
            payload["reply_to"] = email.reply_to
        return await self._retrying(self._post, payload, idempotency_key)

    async def get_received(self, email_id: str) -> ReceivedEmail:
        return await self._retrying(self._get_received, email_id)

    async def _retrying[T](self, call: Callable[..., Awaitable[T]], *args: Any) -> T:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(RETRY_ATTEMPTS),
            wait=RETRY_WAIT,
            retry=retry_if_exception(_is_transient),
            reraise=True,
        )
        try:
            return await retrying(call, *args)
        except (_TransientStatus, httpx.TransportError) as exc:
            raise EmailUnavailable(f"Resend request failed: {exc}") from exc

    async def _post(self, payload: dict[str, Any], idempotency_key: str) -> str:
        response = await self._http.post(
            RESEND_EMAILS_URL, json=payload, headers={"Idempotency-Key": idempotency_key}
        )
        status_code = response.status_code
        if status_code == RATE_LIMITED or status_code >= SERVER_ERROR:
            raise _TransientStatus(f"{status_code} {_error_message(response)}")
        if response.is_client_error:
            raise EmailRejected(_error_message(response))
        try:
            return str(response.json()["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise EmailUnavailable(
                f"Resend answered {status_code} without an email id: {response.text[:200]}"
            ) from exc

    async def _get_received(self, email_id: str) -> ReceivedEmail:
        response = await self._http.get(f"{RESEND_RECEIVED_URL}/{email_id}")
        status_code = response.status_code
        if status_code == RATE_LIMITED or status_code >= SERVER_ERROR:
            raise _TransientStatus(f"{status_code} {_error_message(response)}")
        if response.is_client_error:
            raise EmailRejected(_error_message(response))
        try:
            return ReceivedEmail.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise EmailUnavailable(
                f"Resend answered {status_code} with an unreadable email: {response.text[:200]}"
            ) from exc

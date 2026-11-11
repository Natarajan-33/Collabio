"""PayPal REST adapter (sandbox): Orders v2 checkout, Payouts, refunds, webhook checks.

Tokens come from the client id and secret and are cached until 5 minutes before they
expire; a 401 refreshes once. Every POST carries a fresh `PayPal-Request-Id`, and 429/5xx
are retried. Errors surface as `PayPalError` with PayPal's issue code and debug id.
"""

import time
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Protocol

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

TOKEN_MARGIN_S = 300
RETRYABLE = {429, 500, 502, 503, 504}


class PayPalError(Exception):
    def __init__(
        self, code: str, message: str, *, http_status: int, debug_id: str | None = None
    ) -> None:
        super().__init__(f"{code}: {message} (debug {debug_id})")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.debug_id = debug_id


class _Retryable(Exception):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(response.status_code)
        self.response = response


def cents_to_value(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def value_to_cents(value: str) -> int:
    return int((Decimal(value) * 100).to_integral_value())


class PayPalPort(Protocol):
    async def create_order(
        self,
        *,
        amount_cents: int,
        custom_id: str,
        invoice_id: str,
        description: str,
        return_url: str,
        cancel_url: str,
    ) -> dict[str, Any]: ...
    async def get_order(self, order_id: str) -> dict[str, Any]: ...
    async def capture_order(self, order_id: str) -> dict[str, Any]: ...
    async def refund_capture(
        self, capture_id: str, amount_cents: int, note: str
    ) -> dict[str, Any]: ...
    async def create_payout(
        self, sender_batch_id: str, receiver_email: str, amount_cents: int, note: str
    ) -> dict[str, Any]: ...
    async def get_payout_batch(self, batch_id: str) -> dict[str, Any]: ...
    async def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, webhook_id: str
    ) -> bool: ...


class PayPalClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("PayPal client id and secret are required")
        self._auth = (client_id, client_secret)
        self._base = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=30)
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def _access_token(self, *, force: bool = False) -> str:
        if not force and self._token and time.monotonic() < self._token_expires_at:
            return self._token
        r = await self._http.post(
            f"{self._base}/v1/oauth2/token",
            auth=self._auth,
            data={"grant_type": "client_credentials"},
        )
        if r.status_code != 200:
            raise _error(r)
        body = r.json()
        self._token = body["access_token"]
        self._token_expires_at = time.monotonic() + int(body["expires_in"]) - TOKEN_MARGIN_S
        return self._token

    async def _send(self, method: str, path: str, json: Any | None) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if method == "POST":
            headers["PayPal-Request-Id"] = str(uuid.uuid4())
        for attempt in range(2):
            token = await self._access_token(force=attempt == 1)
            r = await self._http.request(
                method,
                f"{self._base}{path}",
                json=json,
                headers={**headers, "Authorization": f"Bearer {token}"},
            )
            if r.status_code != 401:
                break
        if r.status_code in RETRYABLE:
            raise _Retryable(r)
        return r

    async def _request(self, method: str, path: str, json: Any | None = None) -> dict[str, Any]:
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(lambda e: isinstance(e, _Retryable)),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.2, max=2),
                reraise=True,
            ):
                with attempt:
                    r = await self._send(method, path, json)
        except _Retryable as exc:
            raise _error(exc.response) from None
        if r.status_code >= 300:
            raise _error(r)
        return r.json() if r.content else {}

    async def create_order(
        self,
        *,
        amount_cents: int,
        custom_id: str,
        invoice_id: str,
        description: str,
        return_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": custom_id,
                    "custom_id": custom_id,
                    "invoice_id": invoice_id,
                    "description": description[:127],
                    "amount": {"currency_code": "USD", "value": cents_to_value(amount_cents)},
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": "Collabio",
                        "user_action": "PAY_NOW",
                        "shipping_preference": "NO_SHIPPING",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }
        data = await self._request("POST", "/v2/checkout/orders", body)
        approve = next(
            (link["href"] for link in data.get("links", []) if link.get("rel") == "payer-action"),
            None,
        )
        return {"id": data["id"], "status": data["status"], "approve_url": approve}

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v2/checkout/orders/{order_id}")

    async def capture_order(self, order_id: str) -> dict[str, Any]:
        data = await self._request("POST", f"/v2/checkout/orders/{order_id}/capture", None)
        capture = data["purchase_units"][0]["payments"]["captures"][0]
        return {
            "status": data["status"],
            "capture_id": capture["id"],
            "amount_cents": value_to_cents(capture["amount"]["value"]),
            "custom_id": capture.get("custom_id"),
        }

    async def refund_capture(self, capture_id: str, amount_cents: int, note: str) -> dict[str, Any]:
        data = await self._request(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            {
                "amount": {"currency_code": "USD", "value": cents_to_value(amount_cents)},
                "note_to_payer": note[:255],
            },
        )
        return {"id": data["id"], "status": data["status"]}

    async def create_payout(
        self, sender_batch_id: str, receiver_email: str, amount_cents: int, note: str
    ) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/v1/payments/payouts",
            {
                "sender_batch_header": {
                    "sender_batch_id": sender_batch_id,
                    "email_subject": "You've been paid by Collabio",
                    "email_message": note[:255],
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "amount": {"value": cents_to_value(amount_cents), "currency": "USD"},
                        "receiver": receiver_email,
                        "note": note[:4000],
                        "sender_item_id": sender_batch_id,
                    }
                ],
            },
        )
        header = data["batch_header"]
        items = data.get("items") or []
        return {
            "batch_id": header["payout_batch_id"],
            "item_id": items[0].get("payout_item_id") if items else None,
            "batch_status": header["batch_status"],
        }

    async def get_payout_batch(self, batch_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/v1/payments/payouts/{batch_id}")
        items = data.get("items") or [{}]
        return {
            "batch_status": data["batch_header"]["batch_status"],
            "item_id": items[0].get("payout_item_id"),
            "item_status": items[0].get("transaction_status"),
            "errors": items[0].get("errors"),
        }

    async def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, webhook_id: str
    ) -> bool:
        import json

        h = {k.lower(): v for k, v in headers.items()}
        data = await self._request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            {
                "auth_algo": h.get("paypal-auth-algo"),
                "cert_url": h.get("paypal-cert-url"),
                "transmission_id": h.get("paypal-transmission-id"),
                "transmission_sig": h.get("paypal-transmission-sig"),
                "transmission_time": h.get("paypal-transmission-time"),
                "webhook_id": webhook_id,
                "webhook_event": json.loads(body),
            },
        )
        return data.get("verification_status") == "SUCCESS"


def _error(r: httpx.Response) -> PayPalError:
    try:
        body = r.json()
    except ValueError:
        body = {}
    details = body.get("details") or []
    code = (details[0].get("issue") if details else None) or body.get("name") or "PAYPAL_ERROR"
    return PayPalError(
        code,
        body.get("message") or body.get("error_description") or r.reason_phrase,
        http_status=r.status_code,
        debug_id=r.headers.get("paypal-debug-id") or body.get("debug_id"),
    )

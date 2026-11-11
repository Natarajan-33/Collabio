"""Register (or find) the PayPal sandbox webhook for the deployed API and print its id.

Usage: uv run python -m scripts.register_paypal_webhook https://<api-host>
Prints only the webhook id (not a secret). Set it as PAYPAL_WEBHOOK_ID on the API service.
"""

import asyncio
import sys

from app.adapters.paypal import PayPalClient, PayPalError
from app.config import get_settings

EVENTS = [
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
    "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.BLOCKED",
    "PAYMENT.PAYOUTS-ITEM.DENIED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
    "PAYMENT.PAYOUTS-ITEM.CANCELED",
    "PAYMENT.PAYOUTS-ITEM.HELD",
    "PAYMENT.CAPTURE.REFUNDED",
]


async def register(api_base: str) -> str:
    s = get_settings()
    client = PayPalClient(s.paypal_client_id, s.paypal_client_secret, s.paypal_base_url)
    url = f"{api_base.rstrip('/')}/api/v1/webhooks/paypal"
    body = {"url": url, "event_types": [{"name": e} for e in EVENTS]}
    try:
        return (await client._request("POST", "/v1/notifications/webhooks", body))["id"]
    except PayPalError as exc:
        if "ALREADY_EXISTS" not in str(exc.args) and "ALREADY_EXISTS" not in repr(exc):
            raise
    hooks = (await client._request("GET", "/v1/notifications/webhooks")).get("webhooks", [])
    return next(h["id"] for h in hooks if h["url"] == url)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(asyncio.run(register(sys.argv[1])))

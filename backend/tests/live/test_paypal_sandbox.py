"""Live PayPal sandbox checks with the developer's credentials (run with `-m live`).

Buyer approval cannot run headless, so refund and payout use PAYPAL_TEST_CAPTURE_ID, a
capture approved once by hand (the Nov 11 smoke test).
"""

import asyncio
import uuid

import pytest

from app.adapters.paypal import PayPalClient

pytestmark = pytest.mark.live


@pytest.fixture
def paypal(settings):
    if not settings.paypal_client_id:
        pytest.skip("PAYPAL_CLIENT_ID is not set")
    return PayPalClient(
        settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url
    )


async def test_create_order_requires_payer_action(paypal):
    order = await paypal.create_order(
        amount_cents=100,
        custom_id="live-test",
        invoice_id=f"live-{uuid.uuid4().hex[:16]}",
        description="Collabio live test",
        return_url="https://example.com/r",
        cancel_url="https://example.com/c",
    )
    assert order["status"] == "PAYER_ACTION_REQUIRED"
    assert order["approve_url"].startswith("https://www.sandbox.paypal.com/")


async def test_payout_and_refund_on_test_capture(paypal, settings):
    if not settings.paypal_test_capture_id or not settings.paypal_receiver_email:
        pytest.skip("PAYPAL_TEST_CAPTURE_ID or PAYPAL_RECEIVER_EMAIL is not set")
    refund = await paypal.refund_capture(settings.paypal_test_capture_id, 100, "Live test")
    assert refund["status"] in ("COMPLETED", "PENDING")

    sender = f"collabio-live-{uuid.uuid4().hex[:12]}"
    payout = await paypal.create_payout(sender, settings.paypal_receiver_email, 100, "Live test")
    status = None
    for _ in range(18):
        batch = await paypal.get_payout_batch(payout["batch_id"])
        status = batch["item_status"]
        if status in ("SUCCESS", "FAILED", "RETURNED", "BLOCKED"):
            break
        await asyncio.sleep(5)
    assert status == "SUCCESS"

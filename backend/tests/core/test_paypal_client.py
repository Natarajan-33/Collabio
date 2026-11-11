"""The PayPal sandbox REST adapter: token cache, retries, idempotency, error mapping."""

import httpx
import pytest
import respx

from app.adapters.paypal import PayPalClient, PayPalError, cents_to_value, value_to_cents

BASE = "https://api-m.sandbox.paypal.com"


def token_route(mock, expires_in=32400, token="tok-1"):
    return mock.post(f"{BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": token, "expires_in": expires_in})
    )


def make_client():
    return PayPalClient("cid", "secret", BASE)


def test_cents_to_decimal_string():
    assert cents_to_value(12_345) == "123.45"
    assert cents_to_value(100) == "1.00"
    assert cents_to_value(5) == "0.05"
    assert value_to_cents("123.45") == 12_345
    assert value_to_cents("96.02") == 9_602
    assert value_to_cents("1") == 100


@respx.mock
async def test_token_cached_until_5min_before_expiry():
    tok = token_route(respx)
    respx.get(f"{BASE}/v2/checkout/orders/O1").mock(
        return_value=httpx.Response(200, json={"id": "O1", "status": "CREATED"})
    )
    client = make_client()
    await client.get_order("O1")
    await client.get_order("O1")
    assert tok.call_count == 1


@respx.mock
async def test_token_inside_margin_is_not_reused():
    tok = token_route(respx, expires_in=200)  # inside the 5-minute margin
    respx.get(f"{BASE}/v2/checkout/orders/O1").mock(
        return_value=httpx.Response(200, json={"id": "O1", "status": "CREATED"})
    )
    client = make_client()
    await client.get_order("O1")
    await client.get_order("O1")
    assert tok.call_count == 2


@respx.mock
async def test_refreshes_token_once_on_401():
    tok = token_route(respx)
    order = respx.get(f"{BASE}/v2/checkout/orders/O1").mock(
        side_effect=[
            httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"}),
            httpx.Response(200, json={"id": "O1", "status": "CREATED"}),
        ]
    )
    result = await make_client().get_order("O1")
    assert result["id"] == "O1"
    assert tok.call_count == 2
    assert order.call_count == 2


@respx.mock
async def test_every_post_sends_unique_paypal_request_id():
    token_route(respx)
    route = respx.post(f"{BASE}/v2/checkout/orders").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "O1",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "payer-action", "href": "https://sandbox.paypal.com/x"}],
            },
        )
    )
    client = make_client()
    args = {
        "amount_cents": 24_000,
        "custom_id": "deal-1",
        "invoice_id": "inv-1",
        "description": "Deal",
        "return_url": "http://x/r",
        "cancel_url": "http://x/c",
    }
    first = await client.create_order(**args)
    await client.create_order(**{**args, "invoice_id": "inv-2"})
    ids = {call.request.headers["PayPal-Request-Id"] for call in route.calls}
    assert len(ids) == 2
    assert first == {
        "id": "O1",
        "status": "PAYER_ACTION_REQUIRED",
        "approve_url": "https://sandbox.paypal.com/x",
    }
    import json

    body = json.loads(route.calls[0].request.content)
    unit = body["purchase_units"][0]
    assert unit["amount"] == {"currency_code": "USD", "value": "240.00"}
    assert unit["custom_id"] == "deal-1"
    ctx = body["payment_source"]["paypal"]["experience_context"]
    assert ctx["user_action"] == "PAY_NOW"
    assert ctx["shipping_preference"] == "NO_SHIPPING"
    assert "card" not in body["payment_source"]


@respx.mock
async def test_error_maps_to_paypalerror_with_debug_id():
    token_route(respx)
    respx.post(f"{BASE}/v2/checkout/orders/O1/capture").mock(
        return_value=httpx.Response(
            422,
            headers={"paypal-debug-id": "dbg123"},
            json={
                "name": "UNPROCESSABLE_ENTITY",
                "message": "semantically incorrect",
                "details": [{"issue": "PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING"}],
            },
        )
    )
    with pytest.raises(PayPalError) as exc:
        await make_client().capture_order("O1")
    assert exc.value.code == "PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING"
    assert exc.value.debug_id == "dbg123"
    assert exc.value.http_status == 422


@respx.mock
async def test_retries_on_5xx_then_succeeds():
    token_route(respx)
    route = respx.get(f"{BASE}/v1/payments/payouts/B1").mock(
        side_effect=[
            httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"}),
            httpx.Response(
                200,
                json={
                    "batch_header": {"batch_status": "SUCCESS"},
                    "items": [{"payout_item_id": "I1", "transaction_status": "SUCCESS"}],
                },
            ),
        ]
    )
    result = await make_client().get_payout_batch("B1")
    assert route.call_count == 2
    assert result == {
        "batch_status": "SUCCESS",
        "item_id": "I1",
        "item_status": "SUCCESS",
        "errors": None,
    }


@respx.mock
async def test_capture_parses_capture_id_and_custom_id():
    token_route(respx)
    respx.post(f"{BASE}/v2/checkout/orders/O1/capture").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "O1",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAP1",
                                    "status": "COMPLETED",
                                    "custom_id": "deal-1",
                                    "amount": {"currency_code": "USD", "value": "240.00"},
                                }
                            ]
                        }
                    }
                ],
            },
        )
    )
    result = await make_client().capture_order("O1")
    assert result == {
        "status": "COMPLETED",
        "capture_id": "CAP1",
        "amount_cents": 24_000,
        "custom_id": "deal-1",
    }


@respx.mock
async def test_create_payout_and_refund():
    token_route(respx)
    payout = respx.post(f"{BASE}/v1/payments/payouts").mock(
        return_value=httpx.Response(
            201, json={"batch_header": {"payout_batch_id": "B1", "batch_status": "PENDING"}}
        )
    )
    respx.post(f"{BASE}/v2/payments/captures/CAP1/refund").mock(
        return_value=httpx.Response(201, json={"id": "R1", "status": "COMPLETED"})
    )
    client = make_client()
    out = await client.create_payout("collabio-p1", "creator@example.com", 8_000, "Video 1")
    assert out == {"batch_id": "B1", "item_id": None, "batch_status": "PENDING"}
    import json

    body = json.loads(payout.calls[0].request.content)
    assert body["sender_batch_header"]["sender_batch_id"] == "collabio-p1"
    assert body["items"][0]["amount"] == {"value": "80.00", "currency": "USD"}
    assert body["items"][0]["receiver"] == "creator@example.com"
    assert await client.refund_capture("CAP1", 4_000, "Unspent budget") == {
        "id": "R1",
        "status": "COMPLETED",
    }


@respx.mock
async def test_verify_webhook():
    token_route(respx)
    respx.post(f"{BASE}/v1/notifications/verify-webhook-signature").mock(
        return_value=httpx.Response(200, json={"verification_status": "SUCCESS"})
    )
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.paypal.com/cert",
        "paypal-transmission-id": "t1",
        "paypal-transmission-sig": "sig",
        "paypal-transmission-time": "2026-11-11T00:00:00Z",
    }
    assert await make_client().verify_webhook(headers, b'{"id":"WH-1"}', "WHID") is True

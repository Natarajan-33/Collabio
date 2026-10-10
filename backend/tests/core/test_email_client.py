"""ResendClient against a mocked Resend REST API (respx)."""

import json

import httpx
import pytest
from fastapi import HTTPException

from app.adapters import email as email_module
from app.adapters.email import EmailRejected, EmailUnavailable, OutboundEmail, ResendClient
from app.api import deps
from app.config import Settings

URL = "https://api.resend.com/emails"


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(email_module, "RETRY_WAIT", lambda retry_state: 0)


@pytest.fixture
def client() -> ResendClient:
    return ResendClient(Settings(_env_file=None, resend_api_key="k"))


def make_email(**overrides) -> OutboundEmail:
    fields = {
        "to": "priya@creators.io",
        "sender": "Lumen Audio <brand@mail.collabio.app>",
        "reply_to": "t-abc@inbound.collabio.app",
        "subject": "Collab offer",
        "html": "<p>Hi</p>",
        "text": "Hi",
        "headers": {"List-Unsubscribe": "<https://x/unsub>"},
    }
    return OutboundEmail(**{**fields, **overrides})


async def test_send_posts_resend_payload_with_idempotency_key(client, respx_mock):
    route = respx_mock.post(URL).mock(return_value=httpx.Response(200, json={"id": "em_1"}))

    email_id = await client.send(make_email(), idempotency_key="thread:1:email:0")

    assert email_id == "em_1"
    [call] = route.calls
    assert call.request.headers["Authorization"] == "Bearer k"
    assert call.request.headers["Idempotency-Key"] == "thread:1:email:0"
    assert json.loads(call.request.content) == {
        "from": "Lumen Audio <brand@mail.collabio.app>",
        "to": ["priya@creators.io"],
        "subject": "Collab offer",
        "html": "<p>Hi</p>",
        "text": "Hi",
        "reply_to": "t-abc@inbound.collabio.app",
        "headers": {"List-Unsubscribe": "<https://x/unsub>"},
    }


async def test_reply_to_omitted_when_none(client, respx_mock):
    route = respx_mock.post(URL).mock(return_value=httpx.Response(200, json={"id": "em_1"}))

    await client.send(make_email(reply_to=None), idempotency_key="k1")

    body = json.loads(route.calls.last.request.content)
    assert "reply_to" not in body


async def test_422_raises_rejected_without_retry(client, respx_mock):
    route = respx_mock.post(URL).mock(
        return_value=httpx.Response(422, json={"name": "validation_error", "message": "Bad from"})
    )

    with pytest.raises(EmailRejected, match="Bad from"):
        await client.send(make_email(), idempotency_key="k1")

    assert route.call_count == 1


async def test_429_then_200_retries(client, respx_mock):
    route = respx_mock.post(URL).mock(
        side_effect=[
            httpx.Response(429, json={"message": "slow down"}),
            httpx.Response(200, json={"id": "em_2"}),
        ]
    )

    assert await client.send(make_email(), idempotency_key="k1") == "em_2"
    assert route.call_count == 2
    keys = {c.request.headers["Idempotency-Key"] for c in route.calls}
    assert keys == {"k1"}


async def test_network_error_then_200_retries(client, respx_mock):
    route = respx_mock.post(URL).mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={"id": "em_3"})]
    )

    assert await client.send(make_email(), idempotency_key="k1") == "em_3"
    assert route.call_count == 2


async def test_500_three_times_raises_unavailable(client, respx_mock):
    route = respx_mock.post(URL).mock(return_value=httpx.Response(500, json={"message": "boom"}))

    with pytest.raises(EmailUnavailable):
        await client.send(make_email(), idempotency_key="k1")

    assert route.call_count == 3


@pytest.mark.parametrize("status", [501, 507])
async def test_other_5xx_is_retried(client, respx_mock, status):
    route = respx_mock.post(URL).mock(
        side_effect=[
            httpx.Response(status, json={"message": "x"}),
            httpx.Response(200, json={"id": "em_4"}),
        ]
    )

    assert await client.send(make_email(), idempotency_key="k1") == "em_4"
    assert route.call_count == 2


async def test_408_is_rejected_without_retry(client, respx_mock):
    route = respx_mock.post(URL).mock(
        return_value=httpx.Response(408, json={"message": "Request timeout"})
    )

    with pytest.raises(EmailRejected, match="Request timeout"):
        await client.send(make_email(), idempotency_key="k1")

    assert route.call_count == 1


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, text="<html>ok</html>"), httpx.Response(200, json={"no_id": 1})],
)
async def test_a_2xx_without_an_email_id_is_unavailable(client, respx_mock, response):
    respx_mock.post(URL).mock(return_value=response)

    with pytest.raises(EmailUnavailable):
        await client.send(make_email(), idempotency_key="k1")


def test_requires_api_key():
    with pytest.raises(ValueError):
        ResendClient(Settings(_env_file=None, resend_api_key=""))


def test_the_dependency_without_an_api_key_is_503(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(_env_file=None, resend_api_key=""))
    deps.get_email.cache_clear()
    try:
        with pytest.raises(HTTPException) as caught:
            deps.get_email()
    finally:
        deps.get_email.cache_clear()
    assert caught.value.status_code == 503
    assert caught.value.detail == "email_unavailable"

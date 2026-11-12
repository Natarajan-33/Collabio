"""Final review #6: per-visitor (IP) sub-caps under the shared demo personas."""

from types import SimpleNamespace
from uuid import UUID

from app.modules.money.usage import client_ip, ip_key


def req(xff=None, host="10.0.0.1"):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))


def test_client_ip_uses_the_proxy_appended_rightmost_address():
    # A visitor can send their own X-Forwarded-For; Render's proxy appends the real address.
    assert client_ip(req("1.2.3.4, 203.0.113.9")) == "203.0.113.9"
    assert client_ip(req("203.0.113.9")) == "203.0.113.9"


def test_client_ip_falls_back_to_the_socket_peer():
    assert client_ip(req()) == "10.0.0.1"


def test_ip_key_is_a_stable_uuid_per_address():
    assert isinstance(ip_key("203.0.113.9"), UUID)
    assert ip_key("203.0.113.9") == ip_key("203.0.113.9")
    assert ip_key("203.0.113.9") != ip_key("203.0.113.10")

"""ensure_demo_users and the seed command's guards, against a mocked Supabase Auth API."""

import json
import uuid

import httpx
import pytest
import respx

from app.config import Settings
from scripts import seed
from scripts.seed import SeedError, ensure_demo_users

URL = "https://demo-project.supabase.co"
USERS = f"{URL}/auth/v1/admin/users"


def settings(**overrides) -> Settings:
    values = {
        "supabase_url": URL,
        "supabase_secret_key": "sb_secret_test",
        "demo_brand_email": "brand@example.com",
        "demo_password": "pw-for-tests",
        "demo_helper_email": "helper.creator@example.com",
        "demo_helper_phone": "+15555550123",
    }
    return Settings(_env_file=None, **(values | overrides))


def user_json(email: str) -> dict:
    return {"id": str(uuid.uuid4()), "email": email}


def requested_email(request: httpx.Request) -> str:
    return json.loads(request.content)["email"]


@respx.mock
async def test_creates_confirmed_users_with_the_secret_key_header_only():
    route = respx.post(USERS).mock(
        side_effect=lambda request: httpx.Response(200, json=user_json(requested_email(request)))
    )

    demo = await ensure_demo_users(settings())

    bodies = [json.loads(call.request.content) for call in route.calls]
    assert [b["email"] for b in bodies] == [
        "brand@example.com",
        "helper.creator@example.com",
        "helper.creator+arjun@example.com",
    ]
    assert all(b["password"] == "pw-for-tests" and b["email_confirm"] is True for b in bodies)
    for call in route.calls:
        assert call.request.headers["apikey"] == "sb_secret_test"
        assert "authorization" not in call.request.headers
    assert (demo.brand.email, demo.priya.email, demo.arjun.email) == tuple(
        b["email"] for b in bodies
    )
    assert len(set(demo.user_ids)) == 3 and demo.phone == "+15555550123"


@respx.mock
async def test_existing_user_gets_its_password_reset():
    existing = user_json("Brand@Example.com")  # the lookup ignores case

    def create(request: httpx.Request) -> httpx.Response:
        email = requested_email(request)
        if email == "brand@example.com":
            return httpx.Response(422, json={"error_code": "email_exists", "msg": "registered"})
        return httpx.Response(200, json=user_json(email))

    respx.post(USERS).mock(side_effect=create)
    listing = respx.get(USERS).mock(return_value=httpx.Response(200, json={"users": [existing]}))
    reset = respx.put(f"{USERS}/{existing['id']}").mock(
        return_value=httpx.Response(200, json=existing)
    )

    demo = await ensure_demo_users(settings())

    assert str(demo.brand.id) == existing["id"]
    assert listing.called
    assert json.loads(reset.calls.last.request.content) == {
        "password": "pw-for-tests",
        "email_confirm": True,
    }


@respx.mock
async def test_auth_failure_is_a_seed_error_without_secrets():
    respx.post(USERS).mock(return_value=httpx.Response(500, json={"msg": "database is down"}))

    with pytest.raises(SeedError, match="HTTP 500 database is down") as excinfo:
        await ensure_demo_users(settings())

    assert "pw-for-tests" not in str(excinfo.value)


async def test_missing_variables_are_named():
    with pytest.raises(SeedError, match="DEMO_PASSWORD, DEMO_HELPER_EMAIL"):
        await ensure_demo_users(settings(demo_password="", demo_helper_email=""))


async def test_phone_must_be_e164():
    with pytest.raises(SeedError, match="E.164"):
        await ensure_demo_users(settings(demo_helper_phone="555-0123"))


def test_command_requires_reset(capsys):
    with pytest.raises(SystemExit) as excinfo:
        seed.main([])
    assert excinfo.value.code == 2
    assert "--reset" in capsys.readouterr().err


def test_command_names_missing_variables_and_does_nothing_else(monkeypatch, capsys):
    monkeypatch.setattr(
        seed, "get_settings", lambda: settings(demo_brand_email="", demo_helper_phone="")
    )

    assert seed.main(["--reset"]) == 1

    err = capsys.readouterr().err
    assert "DEMO_BRAND_EMAIL, DEMO_HELPER_PHONE" in err
    assert "pw-for-tests" not in err

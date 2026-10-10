"""GET /me and POST /onboarding against the test database."""

from uuid import UUID, uuid4

import pytest

from app.adapters.db import Database
from tests.tokens import auth_header

pytestmark = pytest.mark.db

EMAIL = "maya@test.collabio.invalid"

BRAND = {
    "role": "brand",
    "display_name": "Maya Chen",
    "company_name": "Lumen Audio",
    "category": "consumer_tech",
    "product_name": "Lumen Pods",
    "product_summary": "Wireless earbuds with 40-hour battery and adaptive noise cancelling",
}


def creator_payload(**overrides) -> dict:
    # A fresh handle per test: handles are unique across the whole database.
    return {
        "role": "creator",
        "display_name": "Priya Raman",
        "handle": f"test_{uuid4().hex[:12]}",
        "niches": ["consumer_tech", "beauty"],
        "region": "IN",
        **overrides,
    }


def headers_for(user_id: UUID) -> dict[str, str]:
    return auth_header(user_id, email=EMAIL)


async def test_me_before_onboarding_has_null_role(client, fake_jwks, auth_user):
    # A role in user_metadata is ignored: the role comes only from profiles.
    headers = auth_header(auth_user, email=EMAIL, user_metadata={"role": "brand"})
    r = await client.get("/api/v1/me", headers=headers)
    assert r.status_code == 200
    assert r.json() == {
        "user_id": str(auth_user),
        "email": EMAIL,
        "role": None,
        "display_name": None,
        "brand": None,
        "creator": None,
    }


async def test_brand_onboarding_creates_profile_brand_product(
    client, fake_jwks, auth_user, api_db: Database
):
    headers = headers_for(auth_user)
    r = await client.post("/api/v1/onboarding", json=BRAND, headers=headers)
    assert r.status_code == 200
    me = r.json()
    assert me["role"] == "brand"
    assert me["display_name"] == "Maya Chen"
    assert me["brand"]["company_name"] == "Lumen Audio"
    assert me["brand"]["category"] == "consumer_tech"
    assert me["creator"] is None

    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select b.id as brand_id, b.contact_email, p.name, p.summary, p.category"
            " from public.brands b join public.products p on p.brand_id = b.id"
            " where b.profile_id = $1",
            auth_user,
        )
    assert [dict(row) for row in rows] == [
        {
            "brand_id": UUID(me["brand"]["id"]),
            "contact_email": EMAIL,  # defaults to the sign-in email
            "name": "Lumen Pods",
            "summary": BRAND["product_summary"],
            "category": "consumer_tech",
        }
    ]
    assert (await client.get("/api/v1/me", headers=headers)).json() == me


async def test_creator_onboarding_creates_creator(client, fake_jwks, auth_user, api_db: Database):
    payload = creator_payload(handle="@Test_" + uuid4().hex[:8].upper())
    r = await client.post("/api/v1/onboarding", json=payload, headers=headers_for(auth_user))
    assert r.status_code == 200
    me = r.json()
    handle = payload["handle"].removeprefix("@").lower()
    assert me["role"] == "creator"
    assert me["brand"] is None
    assert me["creator"] == {
        "id": me["creator"]["id"],
        "handle": handle,
        "name": "Priya Raman",
        "niches": ["consumer_tech", "beauty"],
        "region": "IN",
    }
    async with api_db.acquire() as conn:
        email = await conn.fetchval(
            "select email from public.creators where profile_id = $1", auth_user
        )
    assert email == EMAIL  # contact email defaults to the sign-in email


async def test_creator_onboarding_rejects_unknown_niche_422(client, fake_jwks, auth_user):
    headers = headers_for(auth_user)
    r = await client.post(
        "/api/v1/onboarding", json=creator_payload(niches=["astrology"]), headers=headers
    )
    assert r.status_code == 422
    assert (await client.get("/api/v1/me", headers=headers)).json()["role"] is None


async def test_second_onboarding_with_other_role_409(client, fake_jwks, auth_user):
    headers = headers_for(auth_user)
    assert (await client.post("/api/v1/onboarding", json=BRAND, headers=headers)).status_code == 200

    r = await client.post("/api/v1/onboarding", json=creator_payload(), headers=headers)
    assert r.status_code == 409
    assert r.json() == {"detail": "role_locked"}

    me = (await client.get("/api/v1/me", headers=headers)).json()
    assert me["role"] == "brand"
    assert me["creator"] is None


async def test_repeat_onboarding_with_same_role_updates_names(
    client, fake_jwks, auth_user, api_db: Database
):
    headers = headers_for(auth_user)
    first = await client.post("/api/v1/onboarding", json=BRAND, headers=headers)
    renamed = {**BRAND, "display_name": "Maya C.", "company_name": "Lumen Audio Inc."}
    r = await client.post("/api/v1/onboarding", json=renamed, headers=headers)
    assert r.status_code == 200
    me = r.json()
    assert me["display_name"] == "Maya C."
    assert me["brand"]["company_name"] == "Lumen Audio Inc."
    assert me["brand"]["id"] == first.json()["brand"]["id"]

    async with api_db.acquire() as conn:
        counts = await conn.fetchrow(
            "select count(distinct b.id) as brands, count(p.id) as products"
            " from public.brands b left join public.products p on p.brand_id = b.id"
            " where b.profile_id = $1",
            auth_user,
        )
    assert dict(counts) == {"brands": 1, "products": 1}


async def test_creator_onboarding_with_taken_handle_409(
    client, fake_jwks, auth_user, api_db: Database
):
    handle = f"test_{uuid4().hex[:12]}"
    async with api_db.acquire() as conn:
        # A seeded creator without a login already holds the handle.
        other_id = await conn.fetchval(
            "insert into public.creators (handle, name) values ($1, 'Seeded') returning id",
            handle,
        )
    try:
        headers = headers_for(auth_user)
        r = await client.post(
            "/api/v1/onboarding", json=creator_payload(handle=handle), headers=headers
        )
        assert r.status_code == 409
        assert r.json() == {"detail": "handle_taken"}
        # The whole onboarding rolled back: no profile was left behind.
        assert (await client.get("/api/v1/me", headers=headers)).json()["role"] is None
    finally:
        async with api_db.acquire() as conn:
            await conn.execute("delete from public.creators where id = $1", other_id)

"""Bearer-token verification and the role guard."""

import time
from typing import Annotated
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI

from app.adapters.db import Database
from app.api.deps import (
    JWT_LEEWAY_SECONDS,
    AuthenticatedUser,
    CurrentUser,
    authenticated_user,
    current_user,
    get_jwks_client,
    require_role,
)
from tests.tokens import auth_header, make_token

# A key the JWKS does not publish; tokens carry the test kid, so the signature check fails.
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


class UnreachableJWKSClient(jwt.PyJWKClient):
    def __init__(self) -> None:
        super().__init__("https://jwks.test.invalid/.well-known/jwks.json", cache_keys=True)

    def fetch_data(self) -> dict:
        raise jwt.PyJWKClientConnectionError("Fail to fetch data from the url")


@pytest.fixture
def probe(app: FastAPI) -> None:
    """Routes that report what the auth dependencies resolved to."""

    @app.get("/probe/user")
    async def probe_user(
        user: Annotated[AuthenticatedUser, Depends(authenticated_user)],
    ) -> dict[str, str | None]:
        return {"id": str(user.id), "email": user.email}

    @app.get("/probe/brand-only")
    async def probe_brand_only(
        user: Annotated[CurrentUser, Depends(require_role("brand"))],
    ) -> dict[str, str | None]:
        return {"role": user.role}


def assert_invalid_token(r) -> None:
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid_token"}
    assert r.headers["www-authenticate"] == "Bearer"


async def test_missing_token_401(client):
    r = await client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json() == {"detail": "not_authenticated"}
    assert r.headers["www-authenticate"] == "Bearer"


async def test_expired_token_401(client, fake_jwks):
    # Expired by more than the clock-skew allowance.
    assert_invalid_token(
        await client.get(
            "/api/v1/me", headers=auth_header(uuid4(), exp_delta=-(JWT_LEEWAY_SECONDS + 60))
        )
    )


async def test_token_issued_slightly_in_the_future_is_accepted(client, fake_jwks, probe):
    # A server clock a few seconds ahead of ours stamps `iat` in our future; PyJWT
    # rejects that by default ("not yet valid"), which signed every fresh login out.
    user_id = uuid4()
    r = await client.get("/probe/user", headers=auth_header(user_id, iat=int(time.time()) + 20))
    assert r.status_code == 200
    assert r.json()["id"] == str(user_id)


async def test_token_issued_far_in_the_future_401(client, fake_jwks):
    assert_invalid_token(
        await client.get(
            "/api/v1/me",
            headers=auth_header(uuid4(), iat=int(time.time()) + JWT_LEEWAY_SECONDS + 240),
        )
    )


async def test_wrong_audience_401(client, fake_jwks):
    assert_invalid_token(await client.get("/api/v1/me", headers=auth_header(uuid4(), aud="anon")))


async def test_foreign_key_401(client, fake_jwks):
    assert_invalid_token(
        await client.get("/api/v1/me", headers=auth_header(uuid4(), key=OTHER_KEY))
    )


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("not-a-jwt", id="garbage"),
        pytest.param(make_token(None), id="no-sub"),
        pytest.param(make_token(uuid4(), exp_delta=None), id="no-exp"),
        pytest.param(make_token("service-account"), id="sub-not-a-uuid"),
    ],
)
async def test_malformed_token_401(client, fake_jwks, token):
    assert_invalid_token(
        await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    )


async def test_jwks_unreachable_503(app, client):
    jwks_client = UnreachableJWKSClient()
    app.dependency_overrides[get_jwks_client] = lambda: jwks_client
    r = await client.get("/api/v1/me", headers=auth_header(uuid4()))
    assert r.status_code == 503
    assert r.json() == {"detail": "auth_unavailable"}


async def test_valid_token_resolves_user(client, fake_jwks, probe):
    user_id = uuid4()
    r = await client.get("/probe/user", headers=auth_header(user_id, email="maya@example.com"))
    assert r.status_code == 200
    assert r.json() == {"id": str(user_id), "email": "maya@example.com"}


async def test_blank_email_claim_is_none(client, fake_jwks, probe):
    # Phone sign-ups carry an empty email claim.
    r = await client.get("/probe/user", headers=auth_header(uuid4(), email=""))
    assert r.json()["email"] is None


def signed_in_as(app: FastAPI, role: str | None) -> None:
    user = CurrentUser(id=uuid4(), email=None, role=role)
    app.dependency_overrides[current_user] = lambda: user


async def test_require_role_without_role_409(app, client, probe):
    signed_in_as(app, None)
    r = await client.get("/probe/brand-only")
    assert r.status_code == 409
    assert r.json() == {"detail": "onboarding_required"}


async def test_require_role_other_role_403(app, client, probe):
    signed_in_as(app, "creator")
    r = await client.get("/probe/brand-only")
    assert r.status_code == 403
    assert r.json() == {"detail": "wrong_role"}


async def test_require_role_same_role_passes(app, client, probe):
    signed_in_as(app, "brand")
    r = await client.get("/probe/brand-only")
    assert r.status_code == 200
    assert r.json() == {"role": "brand"}


@pytest.mark.db
async def test_role_comes_from_profiles_not_user_metadata(
    client, fake_jwks, probe, auth_user, api_db: Database
):
    headers = auth_header(auth_user, user_metadata={"role": "brand"})
    r = await client.get("/probe/brand-only", headers=headers)
    assert (r.status_code, r.json()) == (409, {"detail": "onboarding_required"})

    async with api_db.acquire() as conn:
        await conn.execute(
            "insert into public.profiles (id, role, display_name) values ($1, 'creator', 'Priya')",
            auth_user,
        )
    r = await client.get("/probe/brand-only", headers=headers)
    assert (r.status_code, r.json()) == (403, {"detail": "wrong_role"})

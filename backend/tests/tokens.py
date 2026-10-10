"""Signed test access tokens and the JWK Set that verifies them.

These helpers live in a plain module, not in conftest.py: pytest imports
tests/conftest.py as the module `conftest`, so `from tests.conftest import ...` would
execute it a second time and mint a second TEST_KEY that the fake JWKS does not publish.
"""

import time
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

TEST_KID = "collabio-test-key"
TEST_KEY = ec.generate_private_key(ec.SECP256R1())
TEST_JWKS: dict[str, Any] = {
    "keys": [
        {
            **ECAlgorithm.to_jwk(TEST_KEY.public_key(), as_dict=True),
            "kid": TEST_KID,
            "alg": "ES256",
            "use": "sig",
        }
    ]
}


def make_token(
    sub: UUID | str | None,
    *,
    exp_delta: int | None = 3600,
    aud: str = "authenticated",
    key: ec.EllipticCurvePrivateKey = TEST_KEY,
    **claims: Any,
) -> str:
    """An ES256 access token shaped like Supabase's, signed by `key` under TEST_KID.

    `sub=None` or `exp_delta=None` leaves that claim out. Extra keyword arguments
    become claims, e.g. `email=...` or `user_metadata={...}`.
    """
    now = int(time.time())
    payload: dict[str, Any] = {"aud": aud, "iat": now, "role": "authenticated", **claims}
    if sub is not None:
        payload["sub"] = str(sub)
    if exp_delta is not None:
        payload["exp"] = now + exp_delta
    return jwt.encode(payload, key, algorithm="ES256", headers={"kid": TEST_KID})


def auth_header(sub: UUID | str | None, **kwargs: Any) -> dict[str, str]:
    """An Authorization header carrying `make_token(sub, **kwargs)`."""
    return {"Authorization": f"Bearer {make_token(sub, **kwargs)}"}


class StaticJWKSClient(jwt.PyJWKClient):
    """The real PyJWKClient with its HTTP fetch replaced by a fixed JWK Set."""

    def __init__(self, jwk_set: dict[str, Any]) -> None:
        super().__init__("https://jwks.test.invalid/.well-known/jwks.json", cache_keys=True)
        self._jwk_set = jwk_set

    def fetch_data(self) -> dict[str, Any]:
        return self._jwk_set

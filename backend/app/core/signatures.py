"""ElevenLabs webhook signatures.

The `ElevenLabs-Signature` header looks like `t=<unix>,v0=<hex>`, where `<hex>` is the
HMAC-SHA256 of `"<t>.<raw body>"` under the webhook secret. The body is verified as the bytes
received, before any JSON parsing.
"""

import hashlib
import hmac

DEFAULT_TOLERANCE_S = 1800


def sign_elevenlabs_payload(raw: bytes, secret: str, timestamp: int) -> str:
    """The `ElevenLabs-Signature` header value for `raw`, signed at `timestamp`."""
    digest = hmac.new(
        secret.encode(), f"{timestamp}.{raw.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v0={digest}"


def verify_elevenlabs_signature(
    raw: bytes,
    header: str | None,
    secret: str,
    *,
    now: float,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
) -> bool:
    """True when `header` signs `raw` under `secret` and its timestamp is within `tolerance_s`
    of `now`. A missing or malformed header, a bad digest or an unreadable body is False."""
    if not header or not secret:
        return False
    parts: dict[str, str] = {}
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        parts.setdefault(key, value)
    try:
        timestamp = int(parts["t"])
        provided = parts["v0"]
        expected = sign_elevenlabs_payload(raw, secret, timestamp)
    except (KeyError, ValueError):  # no t or v0, a non-numeric t, or a body that is not UTF-8
        return False
    if abs(now - timestamp) > tolerance_s:
        return False
    return hmac.compare_digest(f"t={timestamp},v0={provided}".encode(), expected.encode())

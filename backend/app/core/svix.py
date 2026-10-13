"""Verifying a Svix-signed webhook (Resend signs its webhooks with Svix)."""

import base64
import hashlib
import hmac
from datetime import datetime


def verify_svix(
    secret: str,
    *,
    msg_id: str,
    timestamp: str,
    signature_header: str,
    body: bytes,
    now: datetime,
    tolerance_s: int = 300,
) -> bool:
    """Whether `signature_header` carries a valid v1 signature of this exact message.

    Rejects a timestamp more than `tolerance_s` seconds from `now`. Never raises: anything
    malformed is simply not valid.
    """
    try:
        sent_at = int(timestamp)
        if abs(now.timestamp() - sent_at) > tolerance_s:
            return False
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
        signed = f"{msg_id}.{timestamp}.".encode() + body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest())
        for candidate in signature_header.split():
            version, _, signature = candidate.partition(",")
            if version == "v1" and hmac.compare_digest(signature.encode(), expected):
                return True
    except ValueError:
        return False
    return False

"""Reply tokens: the unguessable part of the address a creator answers an offer email at."""

import secrets

ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
TOKEN_LENGTH = 16


def new_reply_token() -> str:
    """A random 16-character token of lowercase letters and digits."""
    return "".join(secrets.choice(ALPHABET) for _ in range(TOKEN_LENGTH))


def is_reply_token(value: str) -> bool:
    """Whether `value` has the shape of a reply token: 16 characters of `ALPHABET`."""
    return len(value) == TOKEN_LENGTH and all(c in ALPHABET for c in value)


def reply_address(token: str, domain: str) -> str:
    """The inbound address for a thread's token, e.g. `t-abc@in.collabio.dev`."""
    return f"t-{token}@{domain}"

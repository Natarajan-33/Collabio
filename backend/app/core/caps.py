"""Daily per-user usage caps for the public hackathon demo (spec §3)."""

LIMITS: dict[str, int] = {
    "settlement": 30,
    "agent_message": 40,
    "bonus_preview": 30,
    "voice_session": 15,
}


def cap_for(kind: str) -> int:
    """The daily cap for `kind`; unknown kinds raise KeyError."""
    return LIMITS[kind]

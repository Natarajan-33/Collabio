"""Daily per-user usage caps for the public hackathon demo (spec §3)."""

LIMITS: dict[str, int] = {
    # Per demo persona per day. Every judge shares the same two personas, so these are
    # effectively global; the `_ip` sub-caps below stop one visitor from spending them all.
    "settlement": 60,
    "agent_message": 80,
    # Every model call of the dashboard agent's tool loop (one message makes ~5-15 calls).
    "agent_call": 800,
    # Estimated input tokens sent to the dashboard agent, in thousands (a cost ceiling).
    "agent_ktokens": 2000,
    "bonus_preview": 60,
    "voice_session": 15,
    # Per visitor (IP address) per day.
    "settlement_ip": 10,
    "bonus_preview_ip": 20,
}


def cap_for(kind: str) -> int:
    """The daily cap for `kind`; unknown kinds raise KeyError."""
    return LIMITS[kind]

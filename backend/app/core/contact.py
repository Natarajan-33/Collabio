"""Who may be emailed, and how to address them."""

RESERVED_DOMAINS = ("example.com", "example.net", "example.org", "localhost")
RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost")


def is_reserved_address(email: str | None) -> bool:
    """True for a missing address or one on a reserved domain: nothing is sent to these.

    Reserved are `example.com/.net/.org` and their subdomains, `localhost`, and any domain
    ending in `.example`, `.test`, `.invalid` or `.localhost`.
    """
    if email is None or not email.strip():
        return True
    domain = email.strip().rpartition("@")[2].lower()
    if domain in RESERVED_DOMAINS or domain.endswith(RESERVED_SUFFIXES):
        return True
    return any(domain.endswith(f".{reserved}") for reserved in RESERVED_DOMAINS)


def first_name(name: str) -> str:
    """The first whitespace-separated word of a name."""
    words = name.split()
    return words[0] if words else ""

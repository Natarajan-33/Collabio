"""Money is integer cents, USD only."""


def format_cents(cents: int) -> str:
    """`$1,000` when there are no cents, `$999.50` otherwise; negatives read `-$5`."""
    sign = "-" if cents < 0 else ""
    dollars, rest = divmod(abs(cents), 100)
    amount = f"{dollars:,}" if rest == 0 else f"{dollars:,}.{rest:02d}"
    return f"{sign}${amount}"

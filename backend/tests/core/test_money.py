from app.core.money import format_cents


def test_format_cents():
    assert format_cents(100000) == "$1,000"
    assert format_cents(99950) == "$999.50"
    assert format_cents(40000) == "$400"


def test_format_cents_small_and_large_amounts():
    assert format_cents(0) == "$0"
    assert format_cents(5) == "$0.05"
    assert format_cents(123456789) == "$1,234,567.89"


def test_format_cents_negative():
    assert format_cents(-99950) == "-$999.50"
    assert format_cents(-100000) == "-$1,000"

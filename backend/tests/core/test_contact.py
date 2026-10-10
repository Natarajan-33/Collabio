import pytest

from app.core.contact import first_name, is_reserved_address


@pytest.mark.parametrize(
    "email,reserved",
    [
        ("maya@example.com", True),
        ("a@sub.example.org", True),
        ("x@foo.test", True),
        ("x@host.invalid", True),
        ("x@box.example", True),
        ("x@dev.localhost", True),
        ("x@localhost", True),
        ("MAYA@EXAMPLE.NET", True),
        (None, True),
        ("", True),
        ("   ", True),
        ("priya@gmail.com", False),
        ("me@examples.com", False),
        ("me@notexample.com", False),
    ],
)
def test_is_reserved_address(email, reserved):
    assert is_reserved_address(email) is reserved


def test_first_name_is_the_first_word():
    assert first_name("Priya Sharma") == "Priya"
    assert first_name("  Maya   Lee ") == "Maya"
    assert first_name("Cher") == "Cher"

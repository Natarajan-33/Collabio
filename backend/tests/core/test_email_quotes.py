from pathlib import Path

import pytest

from app.core.email_quotes import html_to_text, parse_reply_address, strip_reply

FIXTURES = Path(__file__).parent / "fixtures" / "replies"
DOMAIN = "in.collabio.dev"
TOKEN = "abcdefghij012345"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["gmail_web", "gmail_mobile", "outlook", "apple_mail", "plain"])
def test_strip_reply_fixture(name):
    assert strip_reply(read(f"{name}.txt")) == read(f"{name}.expected.txt").strip()


def test_strip_reply_keeps_inline_numbers():
    assert strip_reply("3 for $1,200\n\nThanks") == "3 for $1,200\n\nThanks"


def test_strip_reply_handles_crlf():
    assert strip_reply("Yes\r\n\r\n\r\nDeal\r\n> old\r\n") == "Yes\n\nDeal"


def test_strip_reply_outlook_from_sent_header_alone():
    text = (
        "OK at $900\n\nFrom: Lumen <a@b.com>\nSent: Tuesday\nTo: me\nSubject: Offer\n\nold $1,000"
    )
    assert strip_reply(text) == "OK at $900"


def test_strip_reply_from_date_header_variant():
    text = "OK at $900\n\nFrom: Lumen <a@b.com>\nDate: Tue, 13 Oct 2026\nSubject: Offer\n\nold"
    assert strip_reply(text) == "OK at $900"


def test_strip_reply_from_without_sent_is_kept():
    assert strip_reply("From: me, 3 for $1,200\nthanks") == "From: me, 3 for $1,200\nthanks"


def test_strip_reply_original_message_alone():
    assert strip_reply("OK\n-----Original Message-----\nold $1,000") == "OK"


def test_strip_reply_outlook_mobile_rule():
    assert strip_reply("OK\n\n" + "_" * 32 + "\nFrom: x\nold") == "OK"


def test_strip_reply_on_wrote_single_line():
    assert strip_reply("OK\n\nOn Tue, Oct 13, 2026, Lumen <a@b.com> wrote:\n> old") == "OK"


def test_strip_reply_drops_quoted_lines_without_attribution():
    assert strip_reply("Yes\n> old $1,000\nOK") == "Yes\nOK"


def test_strip_reply_on_without_wrote_is_kept():
    assert strip_reply("On Tuesday I can shoot.\nSee you") == "On Tuesday I can shoot.\nSee you"


def test_strip_reply_all_quoted_is_empty():
    assert strip_reply("> only a quote") == ""


def test_html_to_text():
    html = "<p>3 for <b>$1,200</b></p><blockquote>old $1,000</blockquote>"
    assert html_to_text(html) == "3 for $1,200"


def test_html_to_text_breaks_and_entities():
    html = "<div>Hi&nbsp;there</div><div>A &amp; B<br>second</div><ul><li>one</li><li>two</li></ul>"
    assert html_to_text(html) == "Hi there\nA & B\nsecond\none\ntwo"


def test_html_to_text_nested_blockquote_and_style():
    html = "<style>p{}</style>Yes<blockquote>a<blockquote>b</blockquote>c</blockquote>after"
    assert html_to_text(html) == "Yesafter"


def test_parse_reply_address_variants():
    assert parse_reply_address([f"Lumen <T-{TOKEN}@In.Collabio.dev>"], DOMAIN) == TOKEN
    assert parse_reply_address([f"t-{TOKEN}@{DOMAIN}"], DOMAIN) == TOKEN
    assert parse_reply_address([f"t-{TOKEN.upper()}@{DOMAIN}"], DOMAIN) == TOKEN
    assert parse_reply_address([f"t-{TOKEN}@{DOMAIN}"], "IN.collabio.dev") == TOKEN


def test_parse_reply_address_rejects_other_domain_or_bad_token():
    assert parse_reply_address([f"t-{TOKEN}@other.dev"], DOMAIN) is None
    assert parse_reply_address([f"t-{TOKEN[:15]}@{DOMAIN}"], DOMAIN) is None
    assert parse_reply_address([f"t-{TOKEN}x@{DOMAIN}"], DOMAIN) is None
    assert parse_reply_address([f"t-{'!' * 16}@{DOMAIN}"], DOMAIN) is None
    assert parse_reply_address([f"{TOKEN}@{DOMAIN}"], DOMAIN) is None
    assert parse_reply_address([], DOMAIN) is None


def test_parse_reply_address_first_match():
    assert parse_reply_address(["someone@x.com", f"t-{TOKEN}@{DOMAIN}"], DOMAIN) == TOKEN
    other = "zzzzzzzzzz999999"
    assert parse_reply_address([f"t-{TOKEN}@{DOMAIN}", f"t-{other}@{DOMAIN}"], DOMAIN) == TOKEN

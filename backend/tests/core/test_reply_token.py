import re

from app.core.reply_token import is_reply_token, new_reply_token, reply_address


def test_reply_token_shape():
    tokens = [new_reply_token() for _ in range(1000)]

    assert all(len(t) == 16 and re.fullmatch(r"[a-z0-9]{16}", t) for t in tokens)
    assert len(set(tokens)) == 1000


def test_reply_address():
    assert reply_address("abc", "in.collabio.dev") == "t-abc@in.collabio.dev"


def test_token_pattern_matches_a_new_token():
    assert is_reply_token(new_reply_token())


def test_is_reply_token_rejects_wrong_shape():
    assert not is_reply_token("abcdefghij01234")  # 15 characters
    assert not is_reply_token("abcdefghij0123456")  # 17 characters
    assert not is_reply_token("ABCDEFGHIJ012345")  # uppercase is not in the alphabet
    assert not is_reply_token("abcdefghij01234!")

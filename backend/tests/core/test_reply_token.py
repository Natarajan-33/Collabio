import re

from app.core.reply_token import new_reply_token, reply_address


def test_reply_token_shape():
    tokens = [new_reply_token() for _ in range(1000)]

    assert all(len(t) == 16 and re.fullmatch(r"[a-z0-9]{16}", t) for t in tokens)
    assert len(set(tokens)) == 1000


def test_reply_address():
    assert reply_address("abc", "in.collabio.dev") == "t-abc@in.collabio.dev"

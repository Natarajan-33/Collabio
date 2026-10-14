"""Reading a creator reply: HTML to text, quoted history stripped, and the reply-to address parsed."""

import re
from collections.abc import Iterable
from email.utils import getaddresses
from html.parser import HTMLParser

from app.core.reply_token import is_reply_token

_ON_WROTE = re.compile(r"^On .+wrote:$", re.IGNORECASE)
_ORIGINAL_MESSAGE = re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE)
_FROM_HEADER = re.compile(r"^From:", re.IGNORECASE)
_SENT_OR_DATE = re.compile(r"^(Sent|Date):", re.IGNORECASE)
_OUTLOOK_RULE = re.compile(r"^_{10,}$")
_SENT_FROM = re.compile(r"^Sent from my ")

_BREAK_TAGS = frozenset({"br"})
_BLOCK_END_TAGS = frozenset({"p", "div", "li"})
_SKIPPED_TAGS = frozenset({"style", "script", "head"})


def _attribution_length(lines: list[str], i: int) -> int:
    """How many lines an "On ... wrote:" attribution starting at line `i` takes; 0 if none."""
    line = lines[i].strip()
    if _ON_WROTE.match(line):
        return 1
    # Mail clients wrap a long attribution over two or three lines.
    if line.startswith("On "):
        for n in (2, 3):
            joined = " ".join(part.strip() for part in lines[i : i + n])
            if _ON_WROTE.match(joined):
                return n
    return 0


def _starts_quote(lines: list[str], i: int) -> bool:
    """Whether the quoted history (or a signature) begins at line `i`."""
    line = lines[i].strip()
    if _attribution_length(lines, i) or _ORIGINAL_MESSAGE.match(line):
        return True
    if _OUTLOOK_RULE.match(line):
        return True
    if lines[i].rstrip("\r\n") in ("-- ", "--") or _SENT_FROM.match(line):
        return True
    if _FROM_HEADER.match(line):
        return any(_SENT_OR_DATE.match(nxt.strip()) for nxt in lines[i + 1 : i + 5])
    return False


def _inline_answers(lines: list[str]) -> list[str]:
    """The creator's lines written between the quoted (`>`) lines after an attribution.

    Only when the quote really is `>`-marked: anything else after the header is history, so
    nothing is kept. A signature or another header ends the reply.
    """
    first = next((line for line in lines if line.strip()), "")
    if not first.lstrip().startswith(">"):
        return []
    kept: list[str] = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            continue
        if _starts_quote(lines, i):
            break
        kept.append(line)
    return kept


def strip_reply(text: str) -> str:
    """The new text of a reply: quoted history and signature cut off, `>` lines dropped.

    Lines the creator wrote between `>`-quoted lines after an attribution are kept (an inline
    reply). The result is trimmed and runs of blank lines collapse to one.
    """
    lines = text.splitlines()
    cut = next((i for i in range(len(lines)) if _starts_quote(lines, i)), len(lines))
    kept: list[str] = []
    candidates = [line for line in lines[:cut] if not line.lstrip().startswith(">")]
    if cut < len(lines):
        header = _attribution_length(lines, cut)
        if header:
            candidates += _inline_answers(lines[cut + header :])
    for line in candidates:
        line = line.rstrip()
        if not line and kept and not kept[-1]:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._quote_depth = 0
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "blockquote":
            self._quote_depth += 1
        elif tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _BREAK_TAGS and not self._quote_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "blockquote":
            self._quote_depth = max(0, self._quote_depth - 1)
        elif tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_END_TAGS and not self._quote_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._quote_depth and not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Plain text of an HTML reply; quoted `<blockquote>` content is dropped."""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = "".join(extractor.parts).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


def parse_reply_address(addresses: Iterable[str], domain: str) -> str | None:
    """The reply token from the first `t-{token}@{domain}` address, or None.

    Accepts bare and `Name <addr>` forms; the domain and the `t-` prefix match any case, and the
    token is returned in lowercase only when it is exactly 16 characters of the token alphabet.
    """
    wanted = domain.lower()
    for _name, addr in getaddresses(list(addresses)):
        local, _, host = addr.strip().rpartition("@")
        if host.lower() != wanted or local[:2].lower() != "t-":
            continue
        token = local[2:].lower()
        if is_reply_token(token):
            return token
    return None

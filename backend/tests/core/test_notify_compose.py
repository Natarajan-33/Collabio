"""What each notification email says: subjects, lines and links, and no private limit."""

import uuid
from datetime import date
from typing import get_args

from app.adapters.gemini import GeminiInvalidOutput, GeminiUnavailable
from app.modules.notify.compose import (
    CLOSED_FALLBACK,
    ClosedParagraph,
    NotifyContext,
    closed_paragraph,
    compose,
    terms_line,
)
from app.modules.notify.outbox import OutboxKind
from app.schemas.negotiation import NegotiationTerms
from tests.fakes import FakeGemini

THREAD = uuid.UUID(int=1)
BATCH = uuid.UUID(int=2)
DEAL = uuid.UUID(int=3)
FRONTEND = "https://app.test"

TERMS = NegotiationTerms(
    videos=3,
    price_cents=110_000,
    go_live_by=date(2026, 11, 30),
    stance="counter",
    source="in_app",
    confidence=1.0,
)


def ctx(kind: OutboxKind, **overrides) -> NotifyContext:
    values = {
        "kind": kind,
        "thread_id": THREAD,
        "batch_id": BATCH,
        "brand_name": "Lumen Audio",
        "product_name": "Lumen Pods",
        "creator_name": "Priya Raman",
        "creator_first_name": "Priya",
        "to_address": "priya@creator.test",
        "reply_token": "abcdefghij012345",
        "outreach_subject": None,
        "terms": TERMS,
        "note": None,
        "reason": None,
        "deal_id": DEAL,
        "frontend_url": FRONTEND,
        "backend_url": "https://api.test",
        "inbound_domain": "in.test.collabio.dev",
    }
    return NotifyContext(**(values | overrides))


def test_terms_line_full_and_partial():
    assert terms_line(TERMS) == "3 videos · $1,100 · live by Nov 30, 2026"
    assert terms_line(TERMS.model_copy(update={"videos": 1})) == (
        "1 video · $1,100 · live by Nov 30, 2026"
    )
    assert terms_line(TERMS.model_copy(update={"videos": None, "go_live_by": None})) == "$1,100"
    assert terms_line(None) == ""


def test_creator_brand_countered():
    content = compose(
        ctx("creator_brand_countered", outreach_subject="Three short reviews for Lumen Pods")
    )

    assert content.subject == "Re: Three short reviews for Lumen Pods"
    assert content.heading == "Lumen Audio sent a counter-offer"
    assert content.lines == ["3 videos · $1,100 · live by Nov 30, 2026"]
    assert (content.cta_label, content.cta_url) == (
        "Review the offer",
        f"{FRONTEND}/creator/offers/{THREAD}",
    )
    assert content.ai_written is False


def test_creator_brand_countered_without_subject_and_with_note():
    content = compose(ctx("creator_brand_countered", note="Can we do it by the 30th?"))

    assert content.subject == "Lumen Audio sent you a counter-offer"
    assert content.lines == [
        "3 videos · $1,100 · live by Nov 30, 2026",
        "Their note: Can we do it by the 30th?",
    ]


def test_creator_awarded():
    content = compose(ctx("creator_awarded"))

    assert content.subject == "You're booked: Lumen Audio × Lumen Pods"
    assert content.lines[0] == "3 videos · $1,100 · live by Nov 30, 2026"
    assert (content.cta_label, content.cta_url) == (
        "View the deal",
        f"{FRONTEND}/creator/deals/{DEAL}",
    )


def test_creator_closed_uses_paragraph():
    content = compose(ctx("creator_closed"), closed_paragraph="Thanks, Priya. Another time.")

    assert content.subject == "Update on Lumen Audio's offer"
    assert content.lines == ["Thanks, Priya. Another time."]
    assert (content.cta_label, content.cta_url) == ("See your offers", f"{FRONTEND}/creator/offers")


def test_creator_closed_defaults_to_the_fallback():
    content = compose(ctx("creator_closed"))

    assert content.lines == [CLOSED_FALLBACK.format(brand="Lumen Audio", product="Lumen Pods")]


def test_brand_creator_countered():
    content = compose(ctx("brand_creator_countered", note="Rush fee applies"))

    assert content.subject == "Priya Raman countered: 3 videos · $1,100"
    assert content.lines == [
        "3 videos · $1,100 · live by Nov 30, 2026",
        "Their note: Rush fee applies",
    ]
    assert (content.cta_label, content.cta_url) == (
        "Open the board",
        f"{FRONTEND}/brand/batches/{BATCH}?thread={THREAD}",
    )


def test_brand_creator_accepted():
    content = compose(ctx("brand_creator_accepted"))

    assert content.subject == "Priya Raman accepted your offer"
    assert content.cta_url == f"{FRONTEND}/brand/batches/{BATCH}?thread={THREAD}"


def test_brand_creator_declined():
    with_reason = compose(ctx("brand_creator_declined", reason="Booked solid"))
    without = compose(ctx("brand_creator_declined"))

    assert with_reason.subject == "Priya Raman declined your offer"
    assert "Their reason: Booked solid" in with_reason.lines
    assert not any(line.startswith("Their reason") for line in without.lines)


def test_brand_needs_review():
    content = compose(ctx("brand_needs_review", reason="The reply has no price"))

    assert content.subject == "Priya Raman replied — needs your review"
    assert any("The reply has no price" in line for line in content.lines)
    assert content.cta_url == f"{FRONTEND}/brand/batches/{BATCH}?thread={THREAD}"


def test_no_private_limits_in_any_kind():
    # The fixtures never carry a limit; this guards future edits that would add one.
    for kind in get_args(OutboxKind):
        content = compose(ctx(kind, note="n", reason="r"))
        text = " ".join([content.subject, content.heading, *content.lines, content.cta_url])
        assert "1,234" not in text
        assert "123400" not in text
        assert "1234" not in text


def test_every_kind_composes():
    for kind in get_args(OutboxKind):
        content = compose(ctx(kind))
        assert content.subject and content.heading and content.lines and content.cta_url


async def test_closed_paragraph_falls_back_without_gemini():
    text, ai = await closed_paragraph(None, ctx("creator_closed"))

    assert text == CLOSED_FALLBACK.format(brand="Lumen Audio", product="Lumen Pods")
    assert ai is False


async def test_closed_paragraph_uses_gemini_reply():
    gemini = FakeGemini()
    gemini.queue_structured(ClosedParagraph(paragraph="  Thanks   so much, Priya.  "))

    text, ai = await closed_paragraph(gemini, ctx("creator_closed"))

    assert (text, ai) == ("Thanks so much, Priya.", True)
    _, prompt, _ = gemini.calls[0]
    assert "Lumen Audio" in prompt and "Lumen Pods" in prompt and "Priya" in prompt
    assert "Raman" not in prompt  # first name only


async def test_closed_paragraph_falls_back_when_gemini_fails_or_mentions_money():
    class Down(FakeGemini):
        def __init__(self, error: Exception) -> None:
            super().__init__()
            self.error = error

        async def generate_structured(self, **kwargs):
            raise self.error

    fallback = CLOSED_FALLBACK.format(brand="Lumen Audio", product="Lumen Pods")
    for error in (GeminiUnavailable("down"), GeminiInvalidOutput("bad")):
        assert await closed_paragraph(Down(error), ctx("creator_closed")) == (fallback, False)

    pricey = FakeGemini()
    pricey.queue_structured(ClosedParagraph(paragraph="We found someone at $500 instead."))
    assert await closed_paragraph(pricey, ctx("creator_closed")) == (fallback, False)

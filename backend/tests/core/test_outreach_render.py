from datetime import date
from uuid import uuid4

from app.core.delta import compute_delta
from app.modules.outreach.prompts import EmailDraft, OutreachContext
from app.modules.outreach.render import render_email
from app.modules.threads.repo import ThreadRef
from app.schemas.packages import PackageTerms

OFFER_URL = "http://localhost:3000/creator/offers/abc"
UNSUBSCRIBE_URL = "http://localhost:8000/api/v1/unsubscribe/tok123"
DISCLOSURE = "This email was written with AI assistance on behalf of Lumen Audio."
TODAY = date(2026, 10, 10)

PACKAGE = PackageTerms(
    name="Launch Pack",
    content_type="short_video",
    niche="consumer_tech",
    volume_count=2,
    volume_basis="per_contract",
    base_price_cents=80000,
    preferred_channel="email_first",
)


def make_context(creator_name: str = "Priya Sharma") -> OutreachContext:
    package_id = uuid4()
    return OutreachContext(
        thread=ThreadRef(id=uuid4(), batch_id=uuid4(), brand_id=uuid4(), creator_id=uuid4()),
        attempts=0,
        reply_token="tok123",
        brand_name="Lumen Audio",
        product_name="Lumen Pods",
        product_summary="Open-ear earbuds",
        negotiation_ask="Three short reviews",
        deliverables_format="short_video",
        ask_videos=3,
        ask_price_cents=100000,
        go_live_by=date(2026, 11, 9),
        flexibility=["timeline"],
        creator_name=creator_name,
        creator_bio="Reviews gadgets",
        creator_niches=["consumer_tech"],
        creator_email="priya@gmail.com",
        package_id=package_id,
        package=PACKAGE,
        delta=compute_delta(
            package_id,
            PACKAGE,
            ask_videos=3,
            ask_price_cents=100000,
            go_live_by=date(2026, 11, 9),
            today=TODAY,
        ),
    )


def make_draft(**overrides: str) -> EmailDraft:
    fields = {
        "subject": "Lumen Pods: three short videos?",
        "opener": "Your gadget reviews are a great fit.",
        "ask_paragraph": "We would love three short videos by November 9.",
        "rationale": "Your audience loves audio gear.",
    }
    return EmailDraft(**(fields | overrides))


def render(ctx=None, draft=None):
    return render_email(
        ctx or make_context(),
        draft or make_draft(),
        offer_url=OFFER_URL,
        unsubscribe_url=UNSUBSCRIBE_URL,
    )


def test_render_contains_table_link_footer_and_unsubscribe():
    rendered = render()

    assert rendered.subject == "Lumen Pods: three short videos?"
    for body in (rendered.text, rendered.html):
        assert "Review &amp; respond in Collabio" in body or "Review & respond in Collabio" in body
        assert OFFER_URL in body
        assert UNSUBSCRIBE_URL in body
        assert DISCLOSURE in body
        assert "$1,000" in body  # the ask price
        assert "$1,200" in body  # listed for 3 videos: $800 / 2 * 3, estimated
        assert "Launch Pack" in body
    assert "Hi Priya," in rendered.text
    assert "Review & respond in Collabio:" in rendered.text
    assert "Unsubscribe" in rendered.html
    assert rendered.html.count("<tr") == 3


def test_render_escapes_html_in_creator_and_draft_text():
    rendered = render(
        make_context("<b>Maya</b> Lee"), make_draft(opener="Loved <script>alert(1)</script>")
    )

    assert "&lt;b&gt;Maya&lt;/b&gt;" in rendered.html
    assert "<b>Maya</b>" not in rendered.html
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert "<b>Maya</b>" in rendered.text  # plain text is not escaped

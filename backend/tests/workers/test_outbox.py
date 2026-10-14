"""The outbox sender: sends each row once, backs off failures, skips reserved addresses.

The sender uses its own connections, so these tests commit their rows and delete them
afterwards (deleting the auth users cascades to everything). Every `send_due` call is
limited to the test's own threads: the database is shared with the dev backend and other tests.
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import date

import pytest

from app.adapters.db import Database
from app.adapters.email import EmailUnavailable
from app.config import Settings, get_settings
from app.modules.notify import sender
from app.modules.notify.compose import CLOSED_FALLBACK, ClosedParagraph
from app.modules.notify.outbox import OutboxKind, enqueue
from app.modules.threads import repo
from app.schemas.negotiation import NegotiationTerms
from tests.db.conftest import Factory
from tests.fakes import FakeEmail, FakeGemini

pytestmark = pytest.mark.db

INBOUND = "in.test.collabio.dev"
BRAND_EMAIL = "partnerships@lumen.test"
TERMS = NegotiationTerms(
    videos=3,
    price_cents=110_000,
    go_live_by=date(2026, 11, 30),
    stance="counter",
    source="in_app",
    confidence=1.0,
)


@dataclass
class Seeded:
    outbox_id: int
    thread_id: uuid.UUID
    creator_email: str


Seed = Callable[..., Awaitable[Seeded]]


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(
        update={
            "resend_from": "Collabio <notify@test.collabio.dev>",
            "resend_inbound_domain": INBOUND,
        }
    )


@pytest.fixture
def deliverable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every address with some text is deliverable; the seeded rows use reserved ones."""
    monkeypatch.setattr(
        "app.modules.notify.sender.is_reserved_address", lambda e: e is None or not e.strip()
    )


@pytest.fixture
async def seed(db: Database) -> AsyncIterator[Seed]:
    """Commit a brand, creator, brief, batch, thread, event and outbox row; clean up after."""
    user_ids: list[uuid.UUID] = []
    thread_ids: list[uuid.UUID] = []

    async def make(
        kind: OutboxKind = "creator_brand_countered",
        *,
        event_type: str = "brand_counter_sent",
        event_payload: dict | None = None,
        outbox_payload: dict | None = None,
        creator_email: str | None = None,
        brand_email: str | None = BRAND_EMAIL,
        status: str = "awaiting_reply",
    ) -> Seeded:
        async with db.acquire() as conn:
            factory = Factory(conn)
            brand = await factory.brand()
            creator = await factory.creator()
            user_ids.append(brand.profile_id)
            if creator.profile_id is not None:
                user_ids.append(creator.profile_id)
            email = creator_email or f"{uuid.uuid4().hex[:10]}@creators.test"
            await conn.execute(
                "update public.creators set email = $2 where id = $1", creator.id, email
            )
            package_id = await factory.package(creator.id)
            brief_id = await factory.brief(
                brand,
                brand_name="Lumen Audio",
                product_name="Lumen Pods",
                contact_email=brand_email,
            )
            batch_id = await factory.batch(brief_id, brand)
            thread_id = await factory.thread(batch_id, brand, creator, package_id, status=status)
            thread_ids.append(thread_id)
            ref = repo.ThreadRef(thread_id, batch_id, brand.id, creator.id)
            async with conn.transaction():
                event_id = await repo.record_event(
                    conn,
                    ref,
                    type=event_type,
                    actor="brand",
                    payload=event_payload,
                    terms=TERMS,
                )
                await enqueue(
                    conn,
                    kind=kind,
                    thread_id=thread_id,
                    event_id=event_id,
                    payload=outbox_payload,
                )
            outbox_id = await conn.fetchval(
                "select id from public.outbox_emails where thread_id = $1", thread_id
            )
        return Seeded(outbox_id=outbox_id, thread_id=thread_id, creator_email=email)

    try:
        yield make
    finally:
        async with db.acquire() as conn:
            await conn.execute(
                "delete from public.outbox_emails where thread_id = any($1::uuid[])", thread_ids
            )
            await conn.execute("delete from auth.users where id = any($1::uuid[])", user_ids)


async def row_of(db: Database, outbox_id: int):
    async with db.acquire() as conn:
        return await conn.fetchrow("select * from public.outbox_emails where id = $1", outbox_id)


async def due_now(db: Database, outbox_id: int) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "update public.outbox_emails set next_attempt_at = now() where id = $1", outbox_id
        )


async def run(db, email, settings, *seeded: Seeded, gemini=None) -> int:
    return await sender.send_due(
        db,
        email=lambda: email,
        gemini=gemini,
        settings=settings,
        thread_ids=[s.thread_id for s in seeded],
    )


async def test_sends_once_and_marks_sent(db, seed, settings, deliverable):
    row = await seed()
    email = FakeEmail()

    assert await run(db, email, settings, row) == 1
    assert await run(db, email, settings, row) == 0

    assert len(email.sent) == 1
    sent, key = email.sent[0]
    assert key == f"outbox:{row.outbox_id}"
    assert sent.to == row.creator_email
    assert sent.subject == "Lumen Audio sent you a counter-offer"
    assert "3 videos · $1,100 · live by Nov 30, 2026" in sent.text
    stored = await row_of(db, row.outbox_id)
    assert stored["status"] == "sent"
    assert stored["resend_id"] == email.email_id(1)
    assert stored["sent_at"] is not None
    assert stored["attempts"] == 1


async def test_creator_mail_has_reply_to_and_unsubscribe(db, seed, settings, deliverable):
    row = await seed()
    email = FakeEmail()

    await run(db, email, settings, row)

    sent, _ = email.sent[0]
    async with db.acquire() as conn:
        token = await conn.fetchval(
            "select reply_token from public.threads where id = $1", row.thread_id
        )
    assert sent.reply_to == f"t-{token}@{INBOUND}"
    assert (
        sent.headers["List-Unsubscribe"]
        == f"<{settings.public_backend_url}/api/v1/unsubscribe/{token}>"
    )
    assert sent.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert f"/api/v1/unsubscribe/{token}" in sent.html
    assert f"/api/v1/unsubscribe/{token}" in sent.text
    assert "written with AI assistance" not in sent.html


async def test_brand_mail_goes_to_brief_contact(db, seed, settings, deliverable):
    row = await seed("brand_creator_countered", event_type="counter_submitted")
    email = FakeEmail()

    await run(db, email, settings, row)

    sent, _ = email.sent[0]
    assert sent.to == BRAND_EMAIL
    assert sent.reply_to is None
    assert "List-Unsubscribe" not in sent.headers
    assert "unsubscribe" not in sent.html.lower()
    assert sent.subject.startswith("Creator ")
    assert "countered: 3 videos · $1,100" in sent.subject


async def test_brand_mail_without_contact_is_skipped(db, seed, settings, deliverable):
    row = await seed("brand_creator_accepted", event_type="accepted", brand_email=None)
    email = FakeEmail()

    await run(db, email, settings, row)

    assert email.sent == []
    assert (await row_of(db, row.outbox_id))["status"] == "skipped"


async def test_reserved_address_skipped(db, seed, settings):
    row = await seed(creator_email="someone@example.com")  # not patched: the real rule applies
    email = FakeEmail()

    assert await run(db, email, settings, row) == 1

    assert email.sent == []
    stored = await row_of(db, row.outbox_id)
    assert stored["status"] == "skipped"
    assert await run(db, email, settings, row) == 0


async def test_backoff_then_failed(db, seed, settings, deliverable):
    row = await seed()
    email = FakeEmail()
    email.failures[row.creator_email] = EmailUnavailable("resend is down")
    gaps: list[float] = []

    for attempt in range(1, 6):
        assert await run(db, email, settings, row) == 1
        stored = await row_of(db, row.outbox_id)
        assert stored["attempts"] == attempt
        assert stored["last_error"] == "resend is down"
        if attempt < 5:
            assert stored["status"] == "pending"
            async with db.acquire() as conn:
                gaps.append(
                    await conn.fetchval(
                        "select extract(epoch from next_attempt_at - now())"
                        " from public.outbox_emails where id = $1",
                        row.outbox_id,
                    )
                )
            await due_now(db, row.outbox_id)

    assert email.sent == []
    assert gaps == sorted(gaps) and len(set(gaps)) == 4
    for attempt, gap in enumerate(gaps, start=1):
        assert 30 * 2**attempt - 10 < gap <= 30 * 2**attempt  # 30 s x 2^attempts
    assert (await row_of(db, row.outbox_id))["status"] == "failed"
    await due_now(db, row.outbox_id)
    assert await run(db, email, settings, row) == 0  # failed rows are never claimed again


async def test_crash_after_send_does_not_duplicate(db, seed, settings, deliverable):
    row = await seed()
    email = FakeEmail()
    email.crash_after_send = True

    await run(db, email, settings, row)
    assert (await row_of(db, row.outbox_id))["status"] == "pending"
    assert len(email.sent) == 1

    email.crash_after_send = False
    await due_now(db, row.outbox_id)
    await run(db, email, settings, row)

    assert len(email.sent) == 1  # same idempotency key outbox:{id}
    stored = await row_of(db, row.outbox_id)
    assert stored["status"] == "sent"
    assert stored["resend_id"] == email.email_id(1)


async def test_claimed_row_is_leased(db, seed, settings, deliverable):
    row = await seed()
    async with db.acquire() as conn:
        claimed = await conn.fetch(sender.CLAIM, 10, [row.thread_id])
        again = await conn.fetch(sender.CLAIM, 10, [row.thread_id])

    assert [r["id"] for r in claimed] == [row.outbox_id]
    assert claimed[0]["attempts"] == 1
    assert again == []  # leased for five minutes


async def test_action_commits_when_resend_down(db, seed, settings, deliverable):
    row = await seed()
    email = FakeEmail()
    email.failures[row.creator_email] = EmailUnavailable("down")

    await run(db, email, settings, row)

    async with db.acquire() as conn:
        events = await conn.fetchval(
            "select count(*) from public.thread_events where thread_id = $1", row.thread_id
        )
    stored = await row_of(db, row.outbox_id)
    assert events == 1
    assert stored["status"] == "pending"
    assert stored["attempts"] == 1


async def test_one_bad_row_does_not_stop_others(db, seed, settings, deliverable, monkeypatch):
    bad = await seed()
    good = await seed()
    real = sender.load_context

    async def flaky(conn, row, settings):
        if row["thread_id"] == bad.thread_id:
            raise RuntimeError("cannot load")
        return await real(conn, row, settings)

    monkeypatch.setattr(sender, "load_context", flaky)
    email = FakeEmail()

    assert await run(db, email, settings, bad, good) == 2

    assert [sent.to for sent, _ in email.sent] == [good.creator_email]
    bad_row = await row_of(db, bad.outbox_id)
    assert (bad_row["status"], bad_row["last_error"]) == ("pending", "cannot load")
    assert (await row_of(db, good.outbox_id))["status"] == "sent"


async def test_not_configured_from_backs_off(db, seed, settings, deliverable):
    row = await seed()
    email = FakeEmail()

    await run(db, email, settings.model_copy(update={"resend_from": ""}), row)

    stored = await row_of(db, row.outbox_id)
    assert email.sent == []
    assert stored["status"] == "pending"
    assert "RESEND_FROM" in stored["last_error"]


async def test_closed_mail_falls_back_without_gemini(db, seed, settings, deliverable):
    row = await seed(
        "creator_closed", event_type="closed_lost", event_payload={"reason": "withdrawn"}
    )
    email = FakeEmail()

    await run(db, email, settings, row, gemini=None)

    sent, _ = email.sent[0]
    assert sent.subject == "Update on Lumen Audio's offer"
    assert CLOSED_FALLBACK.format(brand="Lumen Audio", product="Lumen Pods") in sent.text
    assert "written with AI assistance" not in sent.text
    assert "written with AI assistance" not in sent.html
    assert "withdrawn" not in sent.text  # the internal reason code is not copy


async def test_closed_mail_ai_footer_when_gemini_writes(db, seed, settings, deliverable):
    row = await seed(
        "creator_closed", event_type="closed_lost", event_payload={"reason": "withdrawn"}
    )
    email = FakeEmail()
    gemini = FakeGemini()
    gemini.queue_structured(
        ClosedParagraph(paragraph="Thank you for your time, we loved your work.")
    )

    await run(db, email, settings, row, gemini=gemini)

    sent, _ = email.sent[0]
    assert "Thank you for your time, we loved your work." in sent.text
    assert "This email was written with AI assistance on behalf of Lumen Audio." in sent.text
    assert "This email was written with AI assistance on behalf of Lumen Audio." in sent.html
    assert CLOSED_FALLBACK.format(brand="Lumen Audio", product="Lumen Pods") not in sent.text


async def test_closed_paragraph_is_reused_on_retry(db, seed, settings, deliverable):
    row = await seed("creator_closed", event_type="closed_lost")
    email = FakeEmail()
    email.crash_after_send = True
    gemini = FakeGemini()
    gemini.queue_structured(ClosedParagraph(paragraph="Thanks again for considering us."))

    await run(db, email, settings, row, gemini=gemini)
    email.crash_after_send = False
    await due_now(db, row.outbox_id)
    await run(db, email, settings, row, gemini=gemini)

    assert len(gemini.calls) == 1  # the retry sends the stored body under the same key
    assert len(email.sent) == 1
    stored = await row_of(db, row.outbox_id)
    assert stored["status"] == "sent"
    assert json.loads(stored["payload"])["closed_paragraph"] == "Thanks again for considering us."


async def test_note_and_reason_come_from_the_event(db, seed, settings, deliverable):
    counter = await seed(event_payload={"note": "Can you start earlier?"})
    declined = await seed(
        "brand_creator_declined",
        event_type="declined",
        event_payload={"reason": "Fully booked"},
    )
    email = FakeEmail()

    await run(db, email, settings, counter, declined)

    by_to = {sent.to: sent for sent, _ in email.sent}
    assert "Their note: Can you start earlier?" in by_to[counter.creator_email].text
    assert "Their reason: Fully booked" in by_to[BRAND_EMAIL].text


async def test_awarded_mail_links_to_the_deal(db, seed, settings, deliverable):
    row = await seed("creator_awarded", event_type="accepted", status="awarded")
    async with db.acquire() as conn:
        factory = Factory(conn)
        deal_id = await factory.deal(row.thread_id, videos=3, price_cents=110_000)
    email = FakeEmail()

    await run(db, email, settings, row)

    sent, _ = email.sent[0]
    assert sent.subject == "You're booked: Lumen Audio × Lumen Pods"
    assert f"/creator/deals/{deal_id}" in sent.text


async def opt_out(db: Database, creator_email: str) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "update public.creators set contact_opt_out = true where email = $1", creator_email
        )


@pytest.mark.parametrize("kind", ["creator_brand_countered", "creator_closed"])
async def test_opted_out_creator_is_not_mailed(db, seed, settings, deliverable, kind):
    row = await seed(kind, status="closed_lost" if kind == "creator_closed" else "awaiting_reply")
    await opt_out(db, row.creator_email)
    email = FakeEmail()

    assert await run(db, email, settings, row) == 1

    assert email.sent == []
    stored = await row_of(db, row.outbox_id)
    assert stored["status"] == "skipped"
    assert stored["last_error"] == "creator unsubscribed"


async def test_opted_out_creator_still_gets_the_booking_without_unsubscribe(
    db, seed, settings, deliverable
):
    row = await seed("creator_awarded", event_type="accepted", status="awarded")
    async with db.acquire() as conn:
        await Factory(conn).deal(row.thread_id, videos=3, price_cents=110_000)
    await opt_out(db, row.creator_email)
    email = FakeEmail()

    await run(db, email, settings, row)

    [(sent, _)] = email.sent
    assert sent.to == row.creator_email
    assert sent.subject.startswith("You're booked")
    assert "List-Unsubscribe" not in sent.headers
    assert "List-Unsubscribe-Post" not in sent.headers
    assert "/unsubscribe/" not in sent.html
    assert "/unsubscribe/" not in sent.text
    assert sent.reply_to is not None  # they can still answer
    assert (await row_of(db, row.outbox_id))["status"] == "sent"


async def test_opted_out_creator_does_not_stop_brand_mail(db, seed, settings, deliverable):
    row = await seed("brand_creator_countered", event_type="counter_submitted")
    await opt_out(db, row.creator_email)
    email = FakeEmail()

    await run(db, email, settings, row)

    assert [sent.to for sent, _ in email.sent] == [BRAND_EMAIL]

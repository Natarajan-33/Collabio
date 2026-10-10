"""send_outreach: draft with Gemini, render, send through Resend, record the outcome."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.adapters.email import EmailRejected
from app.modules.outreach.prompts import EmailDraft
from app.modules.outreach.service import send_outreach
from app.modules.threads.repo import transition

pytestmark = pytest.mark.db

DISCLOSURE = "This email was written with AI assistance on behalf of"
# The seeded Priya may carry a reserved address (DEMO_HELPER_EMAIL is often @example.com), which
# would never reach Resend. These tests need her to look real, so her address is swapped for the
# test and restored afterwards. Only FakeEmail ever receives mail here.
PRIYA_TEST_EMAIL = "priya.raman@outreach-tests.collabio.dev"


@pytest.fixture(autouse=True)
async def priya_has_a_real_address(api_db, launched_batch):
    thread_id = launched_batch.threads["priyareviews"]
    async with api_db.acquire() as conn:
        row = await conn.fetchrow(
            "select c.id, c.email from public.threads t join public.creators c"
            " on c.id = t.creator_id where t.id = $1",
            thread_id,
        )
        await conn.execute(
            "update public.creators set email = $2 where id = $1", row["id"], PRIYA_TEST_EMAIL
        )
    try:
        yield
    finally:
        async with api_db.acquire() as conn:
            await conn.execute(
                "update public.creators set email = $2 where id = $1", row["id"], row["email"]
            )


def draft(subject: str = "Lumen Pods: three short videos?") -> EmailDraft:
    return EmailDraft(
        subject=subject,
        opener="Your gadget reviews are a great fit for Lumen Pods.",
        ask_paragraph="We would love three short videos at $1,000 total, live within a month.",
        rationale="Your audience cares about everyday audio gear.",
    )


async def to_drafting(conn, thread_id: UUID) -> None:
    await transition(conn, thread_id, expected={"queued"}, target="drafting")


async def start(api_db, thread_id: UUID) -> None:
    async with api_db.acquire() as conn:
        await to_drafting(conn, thread_id)


async def run(api_db, thread_id, *, gemini, email, settings) -> None:
    await send_outreach(
        api_db,
        gemini=gemini,
        email=lambda: email,
        settings=settings,
        thread_id=thread_id,
        today=datetime.now(UTC).date(),
    )


async def thread_row(api_db, thread_id):
    async with api_db.acquire() as conn:
        return await conn.fetchrow(
            "select status, last_error, attempts from public.threads where id = $1", thread_id
        )


async def events(api_db, thread_id, *types: str):
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select type, actor, payload, external_id, transcript_id from public.thread_events"
            " where thread_id = $1 and type = any($2::text[]) order by id",
            thread_id,
            list(types),
        )
    return [{**row, "payload": json.loads(row["payload"])} for row in rows]


async def creator_email(api_db, thread_id) -> str:
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select c.email from public.threads t join public.creators c on c.id = t.creator_id"
            " where t.id = $1",
            thread_id,
        )


async def token_of(api_db, thread_id) -> str:
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select reply_token from public.threads where id = $1", thread_id
        )


async def test_send_outreach_sends_once_with_stable_idempotency_key(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings
):
    thread_id = launched_batch.threads["priyareviews"]
    settings = m2_settings.model_copy(update={"resend_inbound_domain": ""})
    await start(api_db, thread_id)
    fake_gemini.queue_structured(draft())

    await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=settings)

    assert len(fake_email.sent) == 1
    sent, key = fake_email.sent[0]
    assert key == f"thread:{thread_id}:email:0"
    assert sent.to == await creator_email(api_db, thread_id)
    assert sent.sender == "Lumen Audio <outreach@test.collabio.dev>"
    assert sent.reply_to is None
    assert sent.subject == "Lumen Pods: three short videos?"
    assert DISCLOSURE in sent.html and DISCLOSURE in sent.text
    token = await token_of(api_db, thread_id)
    unsubscribe_url = f"{settings.public_backend_url}/api/v1/unsubscribe/{token}"
    assert sent.headers == {
        "List-Unsubscribe": f"<{unsubscribe_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    assert unsubscribe_url in sent.text
    assert f"{settings.public_frontend_url}/creator/offers/{thread_id}" in sent.text

    row = await thread_row(api_db, thread_id)
    assert row["status"] == "awaiting_reply"
    assert row["last_error"] is None
    drafted, delivered = await events(api_db, thread_id, "email_drafted", "email_sent")
    assert drafted["type"] == "email_drafted"
    assert drafted["payload"]["attempt"] == 0
    assert drafted["payload"]["subject"] == "Lumen Pods: three short videos?"
    assert drafted["payload"]["body_text"] == sent.text
    assert drafted["payload"]["draft"].keys() == {"opener", "ask_paragraph", "rationale"}
    assert delivered["type"] == "email_sent"
    assert delivered["payload"] == {"delivered": True}
    assert delivered["external_id"] == "email_1"
    async with api_db.acquire() as conn:
        transcript = await conn.fetchrow(
            "select id, kind, external_id, subject, body_text from public.transcripts"
            " where thread_id = $1",
            thread_id,
        )
    assert transcript["kind"] == "email_out"
    assert transcript["external_id"] == "email_1"
    assert transcript["subject"] == sent.subject
    assert transcript["body_text"] == sent.text
    assert delivered["transcript_id"] == transcript["id"]


async def test_reply_to_uses_inbound_domain_when_configured(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings
):
    thread_id = launched_batch.threads["priyareviews"]
    settings = m2_settings.model_copy(update={"resend_inbound_domain": "in.test.collabio.dev"})
    await start(api_db, thread_id)
    fake_gemini.queue_structured(draft())

    await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=settings)

    token = await token_of(api_db, thread_id)
    assert fake_email.sent[0][0].reply_to == f"t-{token}@in.test.collabio.dev"


async def test_reserved_address_records_not_delivered(
    api_db, launched_batch, fake_gemini, m2_settings
):
    thread_id = launched_batch.threads["mayamakestech"]
    await start(api_db, thread_id)
    fake_gemini.queue_structured(draft())

    def no_email():
        raise AssertionError("the email factory must not be called for a reserved address")

    await send_outreach(
        api_db,
        gemini=fake_gemini,
        email=no_email,
        settings=m2_settings,
        thread_id=thread_id,
        today=datetime.now(UTC).date(),
    )

    assert (await thread_row(api_db, thread_id))["status"] == "awaiting_reply"
    drafted, delivered = await events(api_db, thread_id, "email_drafted", "email_sent")
    assert drafted["type"] == "email_drafted"
    assert delivered["payload"] == {"delivered": False}
    async with api_db.acquire() as conn:
        transcripts = await conn.fetchval(
            "select count(*) from public.transcripts where thread_id = $1", thread_id
        )
    assert transcripts == 0


async def test_existing_draft_reused_for_same_attempt(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings
):
    thread_id = launched_batch.threads["priyareviews"]
    await start(api_db, thread_id)
    fake_gemini.queue_structured(draft())
    fake_email.crash_after_send = True

    with pytest.raises(RuntimeError, match="crash"):
        await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=m2_settings)
    assert (await thread_row(api_db, thread_id))["status"] == "drafting"

    fake_email.crash_after_send = False
    await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=m2_settings)

    assert len(fake_gemini.calls) == 1
    assert len(fake_email.sent) == 1
    assert (await thread_row(api_db, thread_id))["status"] == "awaiting_reply"
    assert len(await events(api_db, thread_id, "email_drafted")) == 1
    assert len(await events(api_db, thread_id, "email_sent")) == 1


async def test_email_and_prompt_never_mention_ceiling(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings
):
    thread_id = launched_batch.threads["priyareviews"]
    await start(api_db, thread_id)
    fake_gemini.queue_structured(draft())

    await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=m2_settings)

    system, prompt, _ = fake_gemini.calls[-1]
    sent = fake_email.sent[0][0]
    stored = json.dumps(await events(api_db, thread_id, "email_drafted", "email_sent"), default=str)
    for text in (system, prompt, sent.html, sent.text, stored):
        assert "123400" not in text
        assert "1,234" not in text


async def test_rejected_email_fails_thread_with_reason(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings
):
    thread_id = launched_batch.threads["priyareviews"]
    await start(api_db, thread_id)
    fake_gemini.queue_structured(draft())
    fake_email.failures[await creator_email(api_db, thread_id)] = EmailRejected(
        "Invalid `to` field"
    )

    await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=m2_settings)

    row = await thread_row(api_db, thread_id)
    assert row["status"] == "failed"
    assert row["last_error"] == "Email rejected: Invalid `to` field"
    (failed,) = await events(api_db, thread_id, "failed")
    assert failed["payload"] == {"reason": "Email rejected: Invalid `to` field"}


async def test_missing_gemini_fails_thread(api_db, launched_batch, fake_email, m2_settings):
    thread_id = launched_batch.threads["priyareviews"]
    await start(api_db, thread_id)

    await run(api_db, thread_id, gemini=None, email=fake_email, settings=m2_settings)

    row = await thread_row(api_db, thread_id)
    assert row["status"] == "failed"
    assert row["last_error"] == "Email drafting isn't configured (GEMINI_API_KEY)."
    assert fake_email.sent == []


async def test_invalid_gemini_output_fails_thread(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings
):
    thread_id = launched_batch.threads["priyareviews"]
    await start(api_db, thread_id)
    fake_gemini.queue_structured({"subject": "only a subject"})  # breaks the schema

    await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=m2_settings)

    row = await thread_row(api_db, thread_id)
    assert row["status"] == "failed"
    assert row["last_error"] == "Couldn't write the email (model unavailable). Retry to try again."


async def test_missing_resend_from_fails_thread(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings
):
    thread_id = launched_batch.threads["priyareviews"]
    await start(api_db, thread_id)
    fake_gemini.queue_structured(draft())
    settings = m2_settings.model_copy(update={"resend_from": ""})

    await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=settings)

    row = await thread_row(api_db, thread_id)
    assert row["status"] == "failed"
    assert row["last_error"] == "Email isn't configured (RESEND_FROM)."


async def test_missing_resend_key_fails_thread(api_db, launched_batch, fake_gemini, m2_settings):
    thread_id = launched_batch.threads["priyareviews"]
    await start(api_db, thread_id)
    fake_gemini.queue_structured(draft())

    def no_key():
        raise ValueError("RESEND_API_KEY is not set")

    await send_outreach(
        api_db,
        gemini=fake_gemini,
        email=no_key,
        settings=m2_settings,
        thread_id=thread_id,
        today=datetime.now(UTC).date(),
    )

    row = await thread_row(api_db, thread_id)
    assert row["status"] == "failed"
    assert row["last_error"] == "Email isn't configured (RESEND_API_KEY)."


async def test_thread_not_drafting_is_left_alone(
    api_db, launched_batch, fake_gemini, fake_email, m2_settings
):
    thread_id = launched_batch.threads["priyareviews"]  # still queued

    await run(api_db, thread_id, gemini=fake_gemini, email=fake_email, settings=m2_settings)

    assert (await thread_row(api_db, thread_id))["status"] == "queued"
    assert fake_gemini.calls == [] and fake_email.sent == []

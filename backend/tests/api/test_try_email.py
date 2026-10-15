"""POST /voice/try-email: sample outreach without storing the address."""

import pytest

from app.modules.outreach.prompts import EmailDraft

pytestmark = pytest.mark.db

TRY = "/api/v1/voice/try-email"


async def test_try_email_sends_and_does_not_store_address(
    new_brand_client, try_runs, api_db, fake_gemini, fake_email, m2_settings
):
    fake_gemini.queue_structured(
        EmailDraft(
            subject="Lumen Pods collab",
            opener="Love your reviews.",
            ask_paragraph="Three videos for $1,000.",
            rationale="Strong fit.",
        )
    )
    # Use a real-looking domain; not @example.com (reserved).
    inbox = "demo.tryer@tenvexalabs.in"
    r = await new_brand_client.post(TRY, json={"email": inbox, "scenario": "standard"})
    assert r.status_code == 200, r.text
    assert inbox in r.json()["message"]

    assert len(fake_email.sent) == 1
    (outbound, _) = fake_email.sent[0]
    assert outbound.to == inbox
    assert outbound.subject.startswith("[Collabio sample]")

    async with api_db.acquire() as conn:
        stored = await conn.fetchval("select count(*) from public.creators where email = $1", inbox)
        assert stored == 0

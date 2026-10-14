"""Creator email replies through the Resend `email.received` webhook.

Priya's thread of the held `launched_batch` is moved to `awaiting_reply` with `send_held`
(the `offer` fixture). The webhook carries metadata only; the body comes from `FakeEmail.received`.
Her address is read from the database, never hardcoded.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

import pytest

from app.adapters.email import EmailUnavailable, ReceivedEmail
from app.adapters.gemini import GeminiUnavailable
from app.api.deps import get_settings
from app.modules.negotiation.prompts import StructuredReply
from app.schemas.negotiation import NegotiationTerms
from tests.api.helpers import events_of, force_status, outbox_of, record_brand_counter, thread_row

pytestmark = pytest.mark.db

URL = "/api/v1/webhooks/resend/inbound"
DOMAIN = "in.test.collabio.dev"
SECRET = "whsec_" + base64.b64encode(b"collabio-inbound-test-secret").decode()


def sign(secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


async def signed_post(client, payload, secret: str = SECRET, *, timestamp: int | None = None):
    body = json.dumps(payload).encode()
    msg_id = f"msg_{uuid.uuid4().hex}"
    ts = str(int(time.time()) if timestamp is None else timestamp)
    return await client.post(
        URL,
        content=body,
        headers={
            "content-type": "application/json",
            "svix-id": msg_id,
            "svix-timestamp": ts,
            "svix-signature": sign(secret, msg_id, ts, body),
        },
    )


@pytest.fixture
def inbound_settings(app):
    settings = get_settings().model_copy(
        update={"resend_webhook_secret": SECRET, "resend_inbound_domain": DOMAIN}
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


@dataclass
class Reply:
    thread_id: uuid.UUID
    sent_id: int
    token: str
    creator_email: str

    def event(self, email_id: str, *, to=None, type_="email.received", **data) -> dict:
        return {
            "type": type_,
            "created_at": "2026-10-14T10:00:00.000Z",
            "data": {
                "email_id": email_id,
                "from": self.creator_email,
                "to": to if to is not None else [f"t-{self.token}@{DOMAIN}"],
                "subject": "Re: Collab offer",
                "message_id": "<m@creator.test>",
                "attachments": [],
            }
            | data,
        }


@pytest.fixture
async def reply(offer, api_db, inbound_settings, fake_email, fake_gemini) -> Reply:
    thread_id, sent_id = offer
    async with api_db.acquire() as conn:
        row = await conn.fetchrow(
            "select t.reply_token, c.email from public.threads t"
            " join public.creators c on c.id = t.creator_id where t.id = $1",
            thread_id,
        )
    return Reply(thread_id, sent_id, row["reply_token"], row["email"])


def received(reply: Reply, *, text="3 videos for $1,200", html=None, from_=None, **extra):
    """A body for a fresh email id: (email id, what the fake serves for it)."""
    email_id = f"rcv_{uuid.uuid4().hex}"
    return email_id, ReceivedEmail(
        id=email_id,
        **{"from": from_ or reply.creator_email},
        to=[f"t-{reply.token}@{DOMAIN}"],
        subject="Re: Collab offer",
        text=text,
        html=html,
        **extra,
    )


def reply_terms(**overrides) -> StructuredReply:
    base = {
        "videos": 3,
        "price_cents": 120000,
        "stance": "counter",
        "source": "email",
        "confidence": 0.9,
    }
    summary = overrides.pop("summary", "Counter: 3 videos for $1,200")
    return StructuredReply(terms=NegotiationTerms(**(base | overrides)), summary=summary)


async def deliver(client, fake_email, reply: Reply, **kwargs):
    """Fake the received body and post its webhook; (response, email_id)."""
    email_id, message = received(reply, **kwargs)
    fake_email.received[email_id] = message
    r = await signed_post(client, reply.event(email_id, attachments=message.attachments))
    return r, email_id


async def transcripts_for(api_db, email_id: str) -> list[dict]:
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select kind, subject, body_text, thread_id from public.transcripts"
            " where external_id = $1",
            email_id,
        )
    return [dict(r) for r in rows]


async def reply_events(api_db, thread_id) -> list[dict]:
    return await events_of(api_db, thread_id, "email_received")


async def external_ids(api_db, thread_id) -> list[str]:
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select array_agg(external_id) from public.thread_events"
            " where thread_id = $1 and type = 'email_received'",
            thread_id,
        )


# Signature and routing ----------------------------------------------------------------


async def test_bad_signature_401(client, reply):
    other = "whsec_" + base64.b64encode(b"some-other-secret").decode()

    r = await signed_post(client, reply.event("rcv_x"), other)

    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_signature"


async def test_stale_timestamp_401(client, reply):
    r = await signed_post(client, reply.event("rcv_x"), timestamp=int(time.time()) - 3600)

    assert r.status_code == 401


async def test_unconfigured_503(app, client, reply):
    unconfigured = get_settings().model_copy(
        update={"resend_webhook_secret": "", "resend_inbound_domain": DOMAIN}
    )
    app.dependency_overrides[get_settings] = lambda: unconfigured

    r = await signed_post(client, reply.event("rcv_x"))

    assert r.status_code == 503
    assert r.json()["detail"] == "inbound_unconfigured"


async def test_non_received_event_ignored(client, reply, api_db):
    r = await signed_post(client, reply.event("rcv_x", type_="email.sent"))

    assert r.status_code == 200
    assert r.json() == {"outcome": "ignored"}
    assert await reply_events(api_db, reply.thread_id) == []


async def test_unknown_token_200(client, reply, fake_email, api_db):
    stranger = f"t-{'z' * 16}@{DOMAIN}"
    email_id, message = received(reply)
    fake_email.received[email_id] = message

    r = await signed_post(client, reply.event(email_id, to=[stranger]))
    r_none = await signed_post(client, reply.event(email_id, to=["someone@else.test"]))

    assert r.status_code == r_none.status_code == 200
    assert r.json() == r_none.json() == {"outcome": "unknown_token"}
    assert await transcripts_for(api_db, email_id) == []
    assert await reply_events(api_db, reply.thread_id) == []


async def test_token_found_in_received_for(client, reply, fake_email, fake_gemini, api_db):
    email_id, message = received(reply)
    fake_email.received[email_id] = message
    fake_gemini.queue_structured(reply_terms())

    r = await signed_post(
        client,
        reply.event(email_id, to=["list@creator.test"], received_for=[f"t-{reply.token}@{DOMAIN}"]),
    )

    assert r.json() == {"outcome": "applied"}


# The reply itself ---------------------------------------------------------------------


async def test_counter_reply_applied(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms())

    r, email_id = await deliver(
        client, fake_email, reply, text="3 videos for $1,200\n\nOn Tue, Priya wrote:\n> old"
    )

    assert r.status_code == 200
    assert r.json() == {"outcome": "applied"}
    row = await thread_row(api_db, reply.thread_id)
    assert row["status"] == "countered"
    assert row["latest_terms_source"] == "creator"
    assert json.loads(row["latest_terms"])["price_cents"] == 120000
    [event] = await reply_events(api_db, reply.thread_id)
    assert event["actor"] == "creator"
    assert event["terms"]["source"] == "email"
    assert event["terms"]["price_cents"] == 120000
    assert event["payload"]["summary"] == "Counter: 3 videos for $1,200"
    assert await external_ids(api_db, reply.thread_id) == [email_id]
    [transcript] = await transcripts_for(api_db, email_id)
    assert transcript["kind"] == "email_in"
    assert transcript["body_text"] == "3 videos for $1,200"
    assert transcript["subject"] == "Re: Collab offer"
    assert [o["kind"] for o in await outbox_of(api_db, reply.thread_id)] == [
        "brand_creator_countered"
    ]


async def test_price_only_reply_takes_offer_videos(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms(videos=None))

    r, _ = await deliver(client, fake_email, reply, text="$1,200 works")

    assert r.json() == {"outcome": "applied"}
    latest = json.loads((await thread_row(api_db, reply.thread_id))["latest_terms"])
    assert latest["videos"] == 3  # the brief asked for three
    assert latest["price_cents"] == 120000
    [event] = await reply_events(api_db, reply.thread_id)
    assert event["terms"]["videos"] == 3


async def test_reply_without_price_needs_review(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms(price_cents=None, videos=2))

    r, _ = await deliver(client, fake_email, reply, text="Two videos is better for me")

    assert r.json() == {"outcome": "needs_review"}
    assert (await thread_row(api_db, reply.thread_id))["status"] == "needs_review"
    [event] = await reply_events(api_db, reply.thread_id)
    assert event["payload"]["reason"] == "The reply has no price"
    assert [o["kind"] for o in await outbox_of(api_db, reply.thread_id)] == ["brand_needs_review"]


async def test_accept_reply_records_brand_offer(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms(stance="accept", videos=None, price_cents=None))

    r, _ = await deliver(client, fake_email, reply, text="Sounds good, I accept")

    assert r.json() == {"outcome": "applied"}
    row = await thread_row(api_db, reply.thread_id)
    assert row["status"] == "accepted"
    assert row["latest_terms_source"] == "creator"
    latest = json.loads(row["latest_terms"])
    assert (latest["videos"], latest["price_cents"], latest["stance"]) == (3, 100000, "accept")
    [event] = await reply_events(api_db, reply.thread_id)
    assert event["terms"]["stance"] == "accept"
    assert event["terms"]["price_cents"] == 100000
    assert [o["kind"] for o in await outbox_of(api_db, reply.thread_id)] == [
        "brand_creator_accepted"
    ]


async def test_accept_reply_takes_the_brand_counter(client, reply, fake_email, fake_gemini, api_db):
    await record_brand_counter(api_db, reply.thread_id, 110000)
    fake_gemini.queue_structured(reply_terms(stance="accept", videos=None, price_cents=None))

    await deliver(client, fake_email, reply, text="Deal")

    latest = json.loads((await thread_row(api_db, reply.thread_id))["latest_terms"])
    assert latest["price_cents"] == 110000


async def test_decline_reply(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms(stance="decline", videos=None, price_cents=None))

    r, _ = await deliver(client, fake_email, reply, text="No thanks")

    assert r.json() == {"outcome": "applied"}
    row = await thread_row(api_db, reply.thread_id)
    assert row["status"] == "declined"
    assert [o["kind"] for o in await outbox_of(api_db, reply.thread_id)] == [
        "brand_creator_declined"
    ]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        pytest.param(
            {"stance": "question", "videos": None, "price_cents": None},
            "The creator asked a question",
            id="question",
        ),
        pytest.param(
            {"stance": "no_commitment", "videos": None, "price_cents": None},
            "The creator hasn't taken a position yet",
            id="no_commitment",
        ),
        pytest.param({"stance": "offer"}, "The creator hasn't taken a position yet", id="offer"),
        pytest.param(
            {"confidence": 0.4}, "The reply wasn't clear enough to apply", id="low_confidence"
        ),
    ],
)
async def test_unclear_reply_needs_review(
    client, reply, fake_email, fake_gemini, api_db, overrides, reason
):
    fake_gemini.queue_structured(reply_terms(**overrides))

    r, _ = await deliver(client, fake_email, reply, text="Hmm, what about usage rights?")

    assert r.json() == {"outcome": "needs_review"}
    row = await thread_row(api_db, reply.thread_id)
    assert row["status"] == "needs_review"
    assert row["latest_terms_source"] != "creator"  # the creator's position is unchanged
    [event] = await reply_events(api_db, reply.thread_id)
    assert event["payload"]["reason"] == reason
    assert [o["kind"] for o in await outbox_of(api_db, reply.thread_id)] == ["brand_needs_review"]


async def test_gemini_down_needs_review(
    client, reply, fake_email, fake_gemini, api_db, monkeypatch
):
    async def down(**kwargs):
        raise GeminiUnavailable("down")

    monkeypatch.setattr(fake_gemini, "generate_structured", down)

    r, _ = await deliver(client, fake_email, reply)

    assert r.json() == {"outcome": "needs_review"}
    [event] = await reply_events(api_db, reply.thread_id)
    assert event["payload"]["reason"] == "We couldn't read this reply automatically"
    assert (await thread_row(api_db, reply.thread_id))["status"] == "needs_review"


async def test_empty_reply_needs_review(client, reply, fake_email, fake_gemini, api_db):
    r, _ = await deliver(client, fake_email, reply, text="> only quoted\n> lines")

    assert r.json() == {"outcome": "needs_review"}
    assert fake_gemini.calls == []
    [event] = await reply_events(api_db, reply.thread_id)
    assert event["payload"]["reason"] == "We couldn't read this reply automatically"


async def test_duplicate_delivery_once(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms())
    email_id, message = received(reply)
    fake_email.received[email_id] = message
    payload = reply.event(email_id)

    first = await signed_post(client, payload)
    second = await signed_post(client, payload)

    assert first.json() == {"outcome": "applied"}
    assert second.json() == {"outcome": "duplicate"}
    assert len(await reply_events(api_db, reply.thread_id)) == 1
    assert len(await transcripts_for(api_db, email_id)) == 1
    assert len(fake_gemini.calls) == 1
    assert len(await outbox_of(api_db, reply.thread_id)) == 1


async def test_fetch_failure_503(client, reply, fake_email, api_db):
    email_id, message = received(reply)
    fake_email.received[email_id] = message
    fake_email.received_failure = EmailUnavailable("Resend is down")

    r = await signed_post(client, reply.event(email_id))

    assert r.status_code == 503
    assert r.json()["detail"] == "email_unavailable"
    assert await reply_events(api_db, reply.thread_id) == []
    assert await transcripts_for(api_db, email_id) == []
    assert (await thread_row(api_db, reply.thread_id))["status"] == "awaiting_reply"


async def test_sender_match_ignores_case_and_display_name(
    client, reply, fake_email, fake_gemini, api_db
):
    fake_gemini.queue_structured(reply_terms())

    r, _ = await deliver(
        client, fake_email, reply, from_=f'"Priya R" <{reply.creator_email.upper()}>'
    )

    assert r.json() == {"outcome": "applied"}
    assert (await thread_row(api_db, reply.thread_id))["status"] == "countered"


async def test_other_sender_needs_review(client, reply, fake_email, fake_gemini, api_db):
    r, email_id = await deliver(client, fake_email, reply, from_="someone@else.test")

    assert r.json() == {"outcome": "needs_review"}
    assert fake_gemini.calls == []
    [event] = await reply_events(api_db, reply.thread_id)
    assert event["payload"]["reason"] == "The reply came from an address that isn't the creator's"
    assert (await thread_row(api_db, reply.thread_id))["status"] == "needs_review"
    assert len(await transcripts_for(api_db, email_id)) == 1
    assert [o["kind"] for o in await outbox_of(api_db, reply.thread_id)] == ["brand_needs_review"]


async def test_prompt_excludes_quoted_history(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms())

    await deliver(
        client,
        fake_email,
        reply,
        text="3 for $1,200\n\nOn Tue, Oct 13, 2026 at 9:00 AM Lumen Audio wrote:\n> 3 for $1,000",
    )

    ((_, prompt, _),) = fake_gemini.calls
    body = prompt.split("<<<EMAIL\n", 1)[1].split("\nEMAIL>>>", 1)[0]
    assert "$1,200" in body
    assert "$1,000" not in body
    assert "wrote:" not in prompt


async def test_late_reply_reopens_no_response(client, reply, fake_email, fake_gemini, api_db):
    await force_status(api_db, reply.thread_id, "no_response", event="offer_expired")
    fake_gemini.queue_structured(reply_terms())

    r, _ = await deliver(client, fake_email, reply)

    assert r.json() == {"outcome": "applied"}
    row = await thread_row(api_db, reply.thread_id)
    assert row["status"] == "countered"
    assert row["expires_at"] is None


async def test_reply_after_close_is_recorded_only(client, reply, fake_email, fake_gemini, api_db):
    await force_status(
        api_db,
        reply.thread_id,
        "closed_lost",
        event="closed_lost",
        actor="brand",
        payload={"reason": "withdrawn"},
    )

    r, email_id = await deliver(client, fake_email, reply)

    assert r.json() == {"outcome": "recorded"}
    assert (await thread_row(api_db, reply.thread_id))["status"] == "closed_lost"
    assert len(await reply_events(api_db, reply.thread_id)) == 1
    assert len(await transcripts_for(api_db, email_id)) == 1
    assert await outbox_of(api_db, reply.thread_id) == []
    assert fake_gemini.calls == []


async def test_reply_on_accepted_notifies_brand(client, reply, fake_email, fake_gemini, api_db):
    await force_status(api_db, reply.thread_id, "accepted", event="accepted", actor="creator")

    r, _ = await deliver(client, fake_email, reply)

    assert r.json() == {"outcome": "recorded"}
    assert (await thread_row(api_db, reply.thread_id))["status"] == "accepted"
    assert [o["kind"] for o in await outbox_of(api_db, reply.thread_id)] == ["brand_needs_review"]


async def test_countered_thread_cannot_be_accepted_by_email(
    client, reply, fake_email, fake_gemini, api_db
):
    # countered -> accepted is not a legal move, so the reply waits for the brand instead of
    # failing the webhook.
    await force_status(
        api_db, reply.thread_id, "countered", event="counter_submitted", actor="creator"
    )
    fake_gemini.queue_structured(reply_terms(stance="accept", videos=None, price_cents=None))

    r, _ = await deliver(client, fake_email, reply, text="Fine, I accept your offer")

    assert r.status_code == 200
    assert r.json() == {"outcome": "needs_review"}
    assert (await thread_row(api_db, reply.thread_id))["status"] == "needs_review"


async def test_html_only_reply(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms())

    r, email_id = await deliver(client, fake_email, reply, text=None, html="<p>3 for $1,200</p>")

    assert r.json() == {"outcome": "applied"}
    [transcript] = await transcripts_for(api_db, email_id)
    assert transcript["body_text"] == "3 for $1,200"


async def test_attachments_counted(client, reply, fake_email, fake_gemini, api_db):
    fake_gemini.queue_structured(reply_terms())

    await deliver(client, fake_email, reply, attachments=[{"id": "a1"}, {"id": "a2"}])

    [event] = await reply_events(api_db, reply.thread_id)
    assert event["payload"]["attachments_ignored"] == 2


async def test_the_brand_ceiling_never_reaches_the_prompt(
    client, reply, fake_email, fake_gemini, api_db
):
    fake_gemini.queue_structured(reply_terms())

    await deliver(client, fake_email, reply)

    ((system, prompt, _),) = fake_gemini.calls
    for text in (system, prompt):
        assert "1,234" not in text  # the brief's private ceiling
        assert "123400" not in text

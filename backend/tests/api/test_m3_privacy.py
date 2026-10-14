"""M3 privacy sweep: one full deal loop through the API, then a search for what must not leak.

The loop: Priya's offer is sent; she counters below her floor (confirmed); the brand counters
with a note; she counters again by email (signed webhook); the brand counters once more; she
accepts; the brand awards with edited milestones. Every outbox row is then sent through
FakeEmail. Afterwards:

- the brand's ceiling ($1,234) is absent from everything a creator saw and from every stored
  event, transcript, outbox payload, Gemini prompt and sent email;
- Priya's floor is absent from everything the brand saw and from the same stored places;
- contact details cross sides only in a DealView (`GET /deals/{id}`, and the award response
  that returns the new deal to the brand); phone numbers never cross.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from app.config import get_settings
from app.core.money import format_cents
from app.modules.notify import sender
from tests.api.helpers import events_of, outbox_of, send_held
from tests.api.test_inbound import DOMAIN, SECRET, Reply, deliver, reply_terms

pytestmark = pytest.mark.db

OFFERS = "/api/v1/offers"
THREADS = "/api/v1/threads"
BATCHES = "/api/v1/batches"
DEALS = "/api/v1/deals"

CEILING_CENTS = 123400  # the brief's private ceiling, from `launched_batch`


@dataclass
class Seen:
    """One response a client got."""

    side: str  # "creator" | "brand"
    method: str
    path: str
    status: int
    text: str


class Tap:
    """A signed-in client that remembers every response it was given."""

    def __init__(self, client, side: str, log: list[Seen]) -> None:
        self._client, self._side, self._log = client, side, log

    async def get(self, path: str):
        return self._record("GET", path, await self._client.get(path))

    async def post(self, path: str, body: dict | None = None):
        r = await (self._client.post(path) if body is None else self._client.post(path, json=body))
        return self._record("POST", path, r)

    def _record(self, method: str, path: str, r):
        self._log.append(Seen(self._side, method, path, r.status_code, r.text))
        return r


_HEX_ID = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9]{16,}\b")  # reply tokens, hex ids


def mentions(text: str, *needles: str) -> list[str]:
    """The needles that appear in `text`.

    A raw cents amount (all digits) matches anywhere it is not part of a longer number, so it is
    found in compact JSON (`[110000,123400]`) and after an escaped newline (`\n123400`). A
    formatted amount (`$1,234`, `1,234`) must not sit inside a longer figure. Ids and tokens are
    scrubbed first so a random hex run can never pass for an amount.
    """
    text = _LONG_TOKEN.sub(" ", _HEX_ID.sub(" ", text))
    found = []
    for needle in needles:
        if needle.isdigit():
            pattern = rf"(?<!\d){needle}(?!\d)"
        else:
            pattern = rf"(?<![\d,.]){re.escape(needle)}(?!\d|,\d)"
        if re.search(pattern, text):
            found.append(needle)
    return found


def amount_forms(*cents: int) -> tuple[str, ...]:
    """Raw cents, `$`-formatted dollars and, from $1,000 up, the bare comma form (`1,234`)."""
    forms: list[str] = []
    for c in cents:
        formatted = format_cents(c)
        forms += [str(c), formatted]
        if "," in formatted:
            forms.append(formatted.removeprefix("$"))
    return tuple(dict.fromkeys(forms))


def ceiling_forms() -> tuple[str, ...]:
    return amount_forms(CEILING_CENTS)


def test_matcher_finds_every_form_in_every_shape():
    """The detector's own positive control: each form is found where real responses put it."""
    for cents in (CEILING_CENTS, 85000, 127500, 48000, 110000):
        for form in amount_forms(cents):
            raw = form.isdigit()
            shapes = (
                [f"[110001,{form},2]", f'{{"a":{form}}}', f"x\\n{form}", f" {form} "]
                if raw
                else [f"costs {form} now", f"<b>{form}</b>", f"({form})", f"a\\n{form}."]
            )
            for text in shapes:
                assert mentions(text, form) == [form], (form, text)
    # ... and nothing is found inside a longer figure.
    assert mentions("x 1234000 y $11,234 12,345,234", "123400", "$1,234", "1,234") == []
    assert mentions("id 3f2a123400b1c2d3e4f5a6b7c8d9e0f1", "123400") == []


@pytest.fixture
def inbound(app):
    settings = get_settings().model_copy(
        update={
            "resend_webhook_secret": SECRET,
            "resend_inbound_domain": DOMAIN,
            "resend_from": "Collabio <notify@test.collabio.dev>",
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


@pytest.fixture
def deliverable_notify(monkeypatch):
    """Every address with some text is deliverable (the seeded creators' are reserved);
    only FakeEmail ever receives the mail."""
    monkeypatch.setattr(
        "app.modules.notify.sender.is_reserved_address", lambda e: e is None or not e.strip()
    )


async def test_full_deal_loop_leaks_no_limits_or_contacts(
    brand_client,
    creator_client,
    client,
    launched_batch,
    api_db,
    inbound,
    fake_email,
    fake_gemini,
    deliverable_notify,
):
    log: list[Seen] = []
    creator = Tap(creator_client, "creator", log)
    brand = Tap(brand_client, "brand", log)
    thread_id = launched_batch.threads["priyareviews"]
    all_threads = list(launched_batch.threads.values())

    # What is private, and who the parties are -------------------------------------------
    async with api_db.acquire() as conn:
        floor_row = await conn.fetchrow(
            "select f.floor_price_cents as floor, p.volume_count as volume"
            " from public.threads t join public.packages p on p.id = t.package_id"
            " join public.package_floors f on f.package_id = p.id where t.id = $1",
            thread_id,
        )
        people = await conn.fetch(
            "select handle, email, phone from public.creators where id in"
            " (select creator_id from public.threads where batch_id = $1)",
            launched_batch.batch_id,
        )
        contact_email = await conn.fetchval(
            "select contact_email from public.briefs where id = $1", launched_batch.brief_id
        )
    floor, volume = floor_row["floor"], floor_row["volume"]
    floor_for_three = -(-floor * 3 // volume)  # what the floor means for 3 videos
    priya = next(p for p in people if p["handle"] == "priyareviews")
    creator_emails = [p["email"] for p in people if p["email"]]
    creator_phones = [p["phone"] for p in people if p["phone"]]
    assert contact_email and priya["email"]

    # The loop ------------------------------------------------------------------------------
    sent_id = await send_held(api_db, thread_id)
    await creator.get(OFFERS)
    await creator.get(f"{OFFERS}/counts")
    desk = (await creator.get(f"{OFFERS}/{thread_id}")).json()
    assert desk["status"] == "awaiting_reply"

    # 1. Priya counters below her floor; the first try asks for confirmation.
    below = floor_for_three - 100
    counter_body = {
        "terms": {"videos": 3, "price_cents": below},
        "based_on_event_id": sent_id,
        "note": "Three reviews, filmed in one week",
    }
    assert (
        await creator.post(f"{OFFERS}/{thread_id}/counter/preview", counter_body)
    ).status_code == 200
    refused = await creator.post(f"{OFFERS}/{thread_id}/counter", counter_body)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "below_floor"
    # The app's own numbers: the raw floor on Priya's desk, and (price + shortfall) the floor
    # scaled to three videos. Both must agree with the recomputation the forms were built from.
    assert desk["floor_price_cents"] == floor
    app_scaled_floor = below + refused.json()["detail"]["below_by_cents"]
    assert app_scaled_floor == floor_for_three
    floor_forms = amount_forms(floor, app_scaled_floor)
    r = await creator.post(
        f"{OFFERS}/{thread_id}/counter", counter_body | {"confirm_below_floor": True}
    )
    assert r.status_code == 200, r.text
    first_counter = r.json()["terms_event_id"]
    await brand.get(f"{BATCHES}/{launched_batch.batch_id}")
    await brand.get(f"{THREADS}/{thread_id}")

    # 2. The brand counters with a note.
    brand_terms = {"videos": 3, "price_cents": 110000}
    assert (
        await brand.post(f"{THREADS}/{thread_id}/counter/preview", {"terms": brand_terms})
    ).status_code == 200
    r = await brand.post(
        f"{THREADS}/{thread_id}/counter",
        {
            "terms": brand_terms,
            "based_on_event_id": first_counter,
            "note": "Could we meet closer to the middle?",
        },
    )
    assert r.status_code == 200, r.text
    await creator.get(f"{OFFERS}/{thread_id}")
    await creator.get(OFFERS)

    # 3. Priya answers by email: a signed inbound webhook.
    async with api_db.acquire() as conn:
        token = await conn.fetchval(
            "select reply_token from public.threads where id = $1", thread_id
        )
    inbound_reply = Reply(thread_id, sent_id, token, priya["email"])
    fake_gemini.queue_structured(reply_terms(price_cents=118000))
    r, _ = await deliver(client, fake_email, inbound_reply, text="How about 3 videos for $1,180?")
    assert r.status_code == 200 and r.json() == {"outcome": "applied"}, r.text
    email_counter = (await events_of(api_db, thread_id, "email_received"))[-1]["id"]
    await brand.get(f"{THREADS}/{thread_id}")

    # 4. The brand counters again, and Priya accepts.
    r = await brand.post(
        f"{THREADS}/{thread_id}/counter",
        {"terms": {"videos": 3, "price_cents": 112000}, "based_on_event_id": email_counter},
    )
    assert r.status_code == 200, r.text
    second_brand_counter = r.json()["terms_event_id"]
    r = await creator.post(
        f"{OFFERS}/{thread_id}/accept", {"based_on_event_id": second_brand_counter}
    )
    assert r.status_code == 200, r.text
    accepted = r.json()["terms_event_id"]

    # 5. The brand awards with edited milestones.
    preview = (await brand.post(f"{THREADS}/{thread_id}/award/preview")).json()
    go_live = date.fromisoformat(
        (await brand.get(f"{BATCHES}/{launched_batch.batch_id}")).json()["brief"]["go_live_by"]
    )
    drafts = [
        {
            "seq": seq,
            "title": f"Video {seq}",
            "amount_cents": amount,
            "due_date": (go_live + timedelta(days=3 + 7 * (seq - 1))).isoformat(),
        }
        for seq, amount in enumerate([50000, 31000, 31000], start=1)
    ]
    assert sum(d["amount_cents"] for d in drafts) == 112000
    assert preview["milestones"]
    r = await brand.post(
        f"{THREADS}/{thread_id}/award", {"milestones": drafts, "based_on_event_id": accepted}
    )
    assert r.status_code == 200, r.text
    deal_id = r.json()["id"]

    # 6. Both sides read the deal, and the card.
    for side in (creator, brand):
        assert (await side.get(DEALS)).status_code == 200
        assert (await side.get(f"{DEALS}/{deal_id}")).status_code == 200
    await creator.get(f"{OFFERS}/{thread_id}")
    await brand.get(f"{BATCHES}/{launched_batch.batch_id}")

    # 7. Every outbox row is sent.
    rows = [o for t in all_threads for o in await outbox_of(api_db, t)]
    kinds = {o["kind"] for o in rows}
    assert {
        "brand_creator_countered",
        "creator_brand_countered",
        "brand_creator_accepted",
        "creator_awarded",
    } <= kinds
    settings = get_settings().model_copy(
        update={
            "resend_from": "Collabio <notify@test.collabio.dev>",
            "resend_inbound_domain": DOMAIN,
        }
    )
    sent = await sender.send_due(
        api_db,
        email=lambda: fake_email,
        gemini=None,
        settings=settings,
        limit=100,
        thread_ids=all_threads,
    )
    assert sent == len(rows)
    assert len(fake_email.sent) == len(rows)
    async with api_db.acquire() as conn:
        leftover = await conn.fetchval(
            "select count(*) from public.outbox_emails where thread_id = any($1::uuid[])"
            " and status <> 'sent'",
            all_threads,
        )
    assert leftover == 0

    # What each side was shown ----------------------------------------------------------------
    assert all(s.status in (200, 422) for s in log), [(s.path, s.status) for s in log]

    def deal_view(s: Seen) -> bool:
        """A DealView: the deal read back, or returned by the award that made it."""
        read = s.method == "GET" and s.path == f"{DEALS}/{deal_id}"
        awarded = s.method == "POST" and s.path == f"{THREADS}/{thread_id}/award"
        return read or awarded

    creator_saw = [s for s in log if s.side == "creator"]
    brand_saw = [s for s in log if s.side == "brand"]
    assert len(creator_saw) >= 10 and len(brand_saw) >= 10

    # The detector works: the brand's own ceiling is on its board, and the creator's counter
    # price (just under her floor) is on the brand's side and in the stored events.
    assert any(mentions(s.text, *ceiling_forms()) for s in brand_saw)
    assert any(mentions(s.text, str(below)) for s in brand_saw)
    # ... and the floor forms do match where the floor is legitimately shown: Priya's own desk.
    own_desk = [s for s in creator_saw if '"floor_price_cents"' in s.text]
    assert own_desk and all(mentions(s.text, str(floor)) for s in own_desk)
    assert str(floor) in floor_forms and format_cents(app_scaled_floor) in floor_forms

    for s in creator_saw:
        label = f"{s.method} {s.path}"
        assert not mentions(s.text, *ceiling_forms()), f"ceiling in creator response {label}"
        if not deal_view(s):
            assert contact_email not in s.text, f"brief contact email in {label}"
    for s in brand_saw:
        label = f"{s.method} {s.path}"
        assert not mentions(s.text, *floor_forms), f"floor in brand response {label}"
        for phone in creator_phones:
            assert phone not in s.text, f"phone in {label}"
        if not deal_view(s):
            for address in creator_emails:
                assert address not in s.text, f"creator email in {label}"

    # The deal view is where contact details cross, and only the two parties' own.
    deal_for_creator = next(s for s in creator_saw if deal_view(s)).text
    deal_for_brand = next(s for s in brand_saw if deal_view(s)).text
    assert contact_email in deal_for_creator and priya["email"] in deal_for_brand
    assert not mentions(deal_for_creator, *ceiling_forms())
    assert not mentions(deal_for_brand, *floor_forms)

    # What is stored -------------------------------------------------------------------------
    async with api_db.acquire() as conn:
        stored_events = await conn.fetch(
            "select payload::text as payload, terms::text as terms"
            " from public.thread_events where thread_id = any($1::uuid[])",
            all_threads,
        )
        transcripts = await conn.fetch(
            "select subject, body_text from public.transcripts where thread_id = any($1::uuid[])",
            all_threads,
        )
        outbox_payloads = await conn.fetch(
            "select payload::text as payload from public.outbox_emails"
            " where thread_id = any($1::uuid[])",
            all_threads,
        )
    assert transcripts, "the inbound reply is stored as a transcript"
    stores = {
        "thread_events": json.dumps([[e["payload"], e["terms"]] for e in stored_events]),
        "transcripts": json.dumps([[t["subject"], t["body_text"]] for t in transcripts]),
        "outbox payloads": json.dumps([o["payload"] for o in outbox_payloads]),
        "gemini prompts": json.dumps([[system, prompt] for system, prompt, _ in fake_gemini.calls]),
        "emails": json.dumps([[m.subject, m.html, m.text] for m, _ in fake_email.sent]),
    }
    assert stores["emails"] and stores["thread_events"]
    for name, text in stores.items():
        assert not mentions(text, *ceiling_forms()), f"ceiling in {name}"
        assert not mentions(text, *floor_forms), f"floor in {name}"

    # Mail to a creator never carries the brief's contact email, mail to the brand never
    # carries the creator's.
    for message, _ in fake_email.sent:
        body = message.html + message.text
        if message.to == priya["email"]:
            assert contact_email not in body
        else:
            assert priya["email"] not in body
        for phone in creator_phones:
            assert phone not in body

"""The signed post-call webhook: call completion, transcripts and the privacy of the ceiling."""

import asyncio
import json
import time
from uuid import UUID

import pytest

from app.adapters.elevenlabs import snapshot_from_payload
from app.api.deps import optional_gemini
from app.config import get_settings
from app.core.signatures import sign_elevenlabs_payload
from app.modules.negotiation.completion import complete_call
from app.modules.negotiation.prompts import StructuredCall
from app.modules.threads.repo import claim_queued, set_call_conversation, transition
from app.schemas.negotiation import NegotiationTerms

pytestmark = pytest.mark.db

HOOK = "/api/v1/webhooks/elevenlabs/post-call"
CHECK = "/api/v1/webhooks/elevenlabs/tools/check-counter"
LOG = "/api/v1/webhooks/elevenlabs/tools/log-offer"
TOOL_HEADERS = {"X-Collabio-Tool-Secret": "tool-secret"}

TRANSCRIPT = [
    {"role": "agent", "message": "Hi Arjun", "time_in_call_secs": 0},
    {
        "role": "agent",
        "message": None,
        "time_in_call_secs": 5,
        "tool_calls": [{"tool_name": "check_counter"}],
        "tool_results": [{"result_value": '{"suggested_counter_price_usd": 1100}'}],
    },
    {"role": "user", "message": " three for thirteen hundred ", "time_in_call_secs": 7},
]


def hook_body(conversation_id="conv_1", *, transcript=None, **data):
    return {
        "type": "post_call_transcription",
        "event_timestamp": int(time.time()),
        "data": {
            "conversation_id": conversation_id,
            "status": "done",
            "transcript": TRANSCRIPT if transcript is None else transcript,
            "metadata": {"call_duration_secs": 95},
            "analysis": {"transcript_summary": "Countered at $1,300."},
            "conversation_initiation_client_data": {"dynamic_variables": {}},
            **data,
        },
    }


def signed(body: dict, *, secret="hook-secret", t: int | None = None) -> dict:
    raw = json.dumps(body).encode()
    header = sign_elevenlabs_payload(raw, secret, int(time.time()) if t is None else t)
    return {
        "content": raw,
        "headers": {"ElevenLabs-Signature": header, "Content-Type": "application/json"},
    }


def counter(price_cents=120000, confidence=0.9) -> StructuredCall:
    terms = NegotiationTerms(
        videos=3,
        price_cents=price_cents,
        stance="counter",
        source="call",
        confidence=confidence,
    )
    return StructuredCall(terms=terms, summary="Agreed $1,200 for three videos.")


async def in_call_arjun(api_db, launched_batch, conversation_id="conv_1") -> UUID:
    """Arjun's thread claimed, with a placed call, and answered (`in_call`)."""
    thread_id = launched_batch.threads["arjuntech"]
    async with api_db.acquire() as conn:
        await claim_queued(conn, limit=10, batch_id=launched_batch.batch_id)
        await set_call_conversation(conn, thread_id, conversation_id)
        await transition(conn, thread_id, expected={"calling"}, target="in_call")
    return thread_id


async def thread_row(api_db, thread_id):
    async with api_db.acquire() as conn:
        return await conn.fetchrow(
            "select status, last_error, latest_terms, latest_terms_source"
            " from public.threads where id = $1",
            thread_id,
        )


async def events(api_db, thread_id, *types: str):
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select type, actor, payload, terms, transcript_id, external_id"
            " from public.thread_events where thread_id = $1 and type = any($2::text[])"
            " order by id",
            thread_id,
            list(types),
        )
    return [
        {
            **row,
            "payload": json.loads(row["payload"]),
            "terms": json.loads(row["terms"]) if row["terms"] else None,
        }
        for row in rows
    ]


async def transcripts(api_db, **where):
    column, value = next(iter(where.items()))
    async with api_db.acquire() as conn:
        return await conn.fetch(
            "select id, kind, external_id, turns, summary, body_text, thread_id, brief_id"
            f" from public.transcripts where {column} = $1",
            value,
        )


# Signature and configuration -----------------------------------------------------------


async def test_invalid_signature_401(client, m2_settings):
    for kwargs in (
        signed(hook_body(), secret="wrong"),
        signed(hook_body(), t=int(time.time()) - 3600),
        {"content": b"{}", "headers": {}},
    ):
        response = await client.post(HOOK, **kwargs)
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid_signature"


async def test_unconfigured_503(app, client):
    unconfigured = get_settings().model_copy(update={"elevenlabs_webhook_secret": ""})
    app.dependency_overrides[get_settings] = lambda: unconfigured

    response = await client.post(HOOK, **signed(hook_body(), secret=""))

    assert response.status_code == 503
    assert response.json()["detail"] == "webhook_unconfigured"


async def test_post_call_needs_no_tool_secret(client, m2_settings, api_db):
    response = await client.post(HOOK, **signed({"type": "something_else"}))
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_unknown_conversation_is_200(client, m2_settings, api_db, fake_gemini):
    response = await client.post(HOOK, **signed(hook_body("conv_nobody")))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_gemini.calls == []


async def test_unparseable_signed_body_is_200(client, m2_settings, api_db):
    raw = b"not json"
    header = sign_elevenlabs_payload(raw, "hook-secret", int(time.time()))
    response = await client.post(HOOK, content=raw, headers={"ElevenLabs-Signature": header})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# Call completion -------------------------------------------------------------------------


async def test_post_call_records_call_ended_and_countered(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    fake_gemini.queue_structured(counter())

    response = await client.post(HOOK, **signed(hook_body()))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    row = await thread_row(api_db, thread_id)
    assert row["status"] == "countered"
    assert row["latest_terms_source"] == "creator"
    assert json.loads(row["latest_terms"])["price_cents"] == 120000
    (transcript,) = await transcripts(api_db, thread_id=thread_id)
    assert transcript["kind"] == "call"
    assert transcript["external_id"] == "conv_1"
    assert json.loads(transcript["turns"]) == [
        {"role": "agent", "text": "Hi Arjun", "t": 0.0},
        {"role": "user", "text": "three for thirteen hundred", "t": 7.0},
    ]
    assert transcript["summary"] == "Agreed $1,200 for three videos."
    (ended,) = await events(api_db, thread_id, "call_ended")
    assert ended["transcript_id"] == transcript["id"]
    assert ended["external_id"] == "conv_1"
    assert ended["actor"] == "system"
    assert ended["payload"] == {
        "summary": "Agreed $1,200 for three videos.",
        "duration_secs": 95,
    }
    assert ended["terms"]["price_cents"] == 120000
    assert ended["terms"]["source"] == "call"
    assert await events(api_db, thread_id, "needs_review") == []


async def test_duplicate_post_call_is_one_event(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    fake_gemini.queue_structured(counter())
    request = signed(hook_body())

    first = await client.post(HOOK, **request)
    second = await client.post(HOOK, **request)

    assert first.status_code == second.status_code == 200
    assert len(await events(api_db, thread_id, "call_ended")) == 1
    assert len(await transcripts(api_db, thread_id=thread_id)) == 1
    assert len(fake_gemini.calls) == 1


async def test_concurrent_deliveries_structure_once(api_db, launched_batch, fake_gemini):
    thread_id = await in_call_arjun(api_db, launched_batch)
    fake_gemini.queue_structured(counter())
    snapshot = snapshot_from_payload(hook_body()["data"])

    results = await asyncio.gather(
        *(complete_call(api_db, fake_gemini, "conv_1", snapshot) for _ in range(3))
    )

    assert sorted(results) == [False, False, True]
    assert len(fake_gemini.calls) == 1
    assert len(await events(api_db, thread_id, "call_ended")) == 1


async def test_low_confidence_needs_review(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    fake_gemini.queue_structured(counter(confidence=0.4))

    await client.post(HOOK, **signed(hook_body()))

    assert (await thread_row(api_db, thread_id))["status"] == "needs_review"
    (review,) = await events(api_db, thread_id, "needs_review")
    assert review["payload"] == {"reason": "Low confidence in the call terms."}
    assert len(await events(api_db, thread_id, "call_ended")) == 1


async def test_structurer_failure_needs_review(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    fake_gemini.queue_structured({"terms": {"stance": "bogus"}})

    await client.post(HOOK, **signed(hook_body()))

    assert (await thread_row(api_db, thread_id))["status"] == "needs_review"
    (review,) = await events(api_db, thread_id, "needs_review")
    assert review["payload"] == {"reason": "Couldn't read the call terms."}
    (ended,) = await events(api_db, thread_id, "call_ended")
    assert ended["payload"]["summary"] == "Countered at $1,300."  # ElevenLabs' own summary
    assert ended["terms"] is None
    (transcript,) = await transcripts(api_db, thread_id=thread_id)
    assert transcript["summary"] == "Countered at $1,300."


async def test_no_user_speech_fails_with_no_answer(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    agent_only = [{"role": "agent", "message": "Hello?", "time_in_call_secs": 0}]

    response = await client.post(HOOK, **signed(hook_body(transcript=agent_only)))

    assert response.status_code == 200
    row = await thread_row(api_db, thread_id)
    assert (row["status"], row["last_error"]) == ("failed", "No answer.")
    (failed,) = await events(api_db, thread_id, "failed")
    assert failed["payload"] == {"reason": "No answer."}
    assert failed["external_id"] == "conv_1"
    assert await events(api_db, thread_id, "call_ended") == []
    assert await transcripts(api_db, thread_id=thread_id) == []
    assert fake_gemini.calls == []


async def test_post_call_for_a_finished_thread_is_ignored(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    async with api_db.acquire() as conn:
        await transition(conn, thread_id, expected={"in_call"}, target="failed")

    response = await client.post(HOOK, **signed(hook_body()))

    assert response.status_code == 200
    assert fake_gemini.calls == []
    assert await events(api_db, thread_id, "call_ended") == []


async def test_post_call_without_gemini_needs_review(
    app, client, m2_settings, api_db, launched_batch
):
    app.dependency_overrides[optional_gemini] = lambda: None
    thread_id = await in_call_arjun(api_db, launched_batch)

    await client.post(HOOK, **signed(hook_body()))

    assert (await thread_row(api_db, thread_id))["status"] == "needs_review"


async def test_transcript_drops_tool_results(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    fake_gemini.queue_structured(counter())

    await client.post(HOOK, **signed(hook_body()))

    (transcript,) = await transcripts(api_db, thread_id=thread_id)
    stored = transcript["turns"] + (transcript["summary"] or "")
    assert "1100" not in stored
    assert "check_counter" not in stored
    assert "tool_" not in stored
    _, prompt, _ = fake_gemini.calls[0]
    assert "1100" not in prompt
    assert "check_counter" not in prompt


async def test_ceiling_never_stored_after_full_call(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    checked = await client.post(
        CHECK,
        json={"thread_id": str(thread_id), "price_usd": 1300, "videos": 3},
        headers=TOOL_HEADERS,
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["verdict"] == "over"
    logged = await client.post(
        LOG,
        json={
            "thread_id": str(thread_id),
            "price_usd": 1300,
            "videos": 3,
            "stance": "counter",
            "speaker": "creator",
        },
        headers=TOOL_HEADERS,
    )
    assert logged.status_code == 200, logged.text
    fake_gemini.queue_structured(counter(price_cents=130000))

    await client.post(HOOK, **signed(hook_body()))

    async with api_db.acquire() as conn:
        stored = [
            await conn.fetchval(
                "select coalesce(jsonb_agg(to_jsonb(e)), '[]')::text"
                " from public.thread_events e where thread_id = $1",
                thread_id,
            ),
            await conn.fetchval(
                "select to_jsonb(t)::text from public.threads t where id = $1", thread_id
            ),
            await conn.fetchval(
                "select coalesce(jsonb_agg(to_jsonb(x)), '[]')::text"
                " from public.transcripts x where thread_id = $1",
                thread_id,
            ),
        ]
    stored += [system + prompt for system, prompt, _ in fake_gemini.calls]
    assert len(await events(api_db, thread_id, "call_ended")) == 1
    assert len(fake_gemini.calls) == 1
    for blob in stored:
        assert "123400" not in blob
        assert "$1,234" not in blob


# Failures before the call connects --------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("no-answer", "No answer."),
        ("busy", "Line busy."),
        ("unknown", "Call couldn't connect."),
    ],
)
async def test_call_initiation_failure_fails_thread(
    client, m2_settings, api_db, launched_batch, reason, message
):
    thread_id = launched_batch.threads["arjuntech"]
    async with api_db.acquire() as conn:
        await claim_queued(conn, limit=10, batch_id=launched_batch.batch_id)
        await set_call_conversation(conn, thread_id, "conv_1")
    body = {
        "type": "call_initiation_failure",
        "event_timestamp": int(time.time()),
        "data": {"conversation_id": "conv_1", "failure_reason": reason},
    }

    response = await client.post(HOOK, **signed(body))

    assert response.status_code == 200
    row = await thread_row(api_db, thread_id)
    assert (row["status"], row["last_error"]) == ("failed", message)
    (failed,) = await events(api_db, thread_id, "failed")
    assert failed["payload"] == {"reason": message}
    assert failed["external_id"] == "conv_1"


async def test_call_initiation_failure_on_an_answered_call_changes_nothing(
    client, m2_settings, api_db, launched_batch
):
    thread_id = await in_call_arjun(api_db, launched_batch)
    body = {
        "type": "call_initiation_failure",
        "data": {"conversation_id": "conv_1", "failure_reason": "busy"},
    }

    assert (await client.post(HOOK, **signed(body))).status_code == 200

    assert (await thread_row(api_db, thread_id))["status"] == "in_call"


# Intake -----------------------------------------------------------------------------------


async def test_intake_transcript_stored(client, m2_settings, api_db, launched_batch, fake_gemini):
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.briefs set intake_conversation_id = 'conv_brief' where id = $1",
            launched_batch.brief_id,
        )
    body = hook_body("conv_brief")

    response = await client.post(HOOK, **signed(body))
    again = await client.post(HOOK, **signed(body))

    assert response.status_code == again.status_code == 200
    (transcript,) = await transcripts(api_db, brief_id=launched_batch.brief_id)
    assert transcript["kind"] == "intake"
    assert transcript["thread_id"] is None
    assert transcript["external_id"] == "conv_brief"
    assert [t["text"] for t in json.loads(transcript["turns"])] == [
        "Hi Arjun",
        "three for thirteen hundred",
    ]
    assert transcript["summary"] == "Countered at $1,300."
    assert fake_gemini.calls == []


async def test_intake_found_by_brief_id_variable(
    client, m2_settings, api_db, launched_batch, fake_gemini
):
    body = hook_body(
        "conv_brief_var",
        conversation_initiation_client_data={
            "dynamic_variables": {"brief_id": str(launched_batch.brief_id)}
        },
    )

    await client.post(HOOK, **signed(body))

    (transcript,) = await transcripts(api_db, brief_id=launched_batch.brief_id)
    assert transcript["external_id"] == "conv_brief_var"


async def test_intake_brief_id_that_is_not_a_uuid_is_ignored(
    client, m2_settings, api_db, launched_batch
):
    body = hook_body(
        "conv_brief_bad",
        conversation_initiation_client_data={"dynamic_variables": {"brief_id": "nope"}},
    )

    assert (await client.post(HOOK, **signed(body))).status_code == 200
    assert await transcripts(api_db, brief_id=launched_batch.brief_id) == []

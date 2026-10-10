"""start_call: place the agent's outbound call for a `calling` thread, or fail it with a reason."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.adapters.elevenlabs import CallPlacementFailed, ElevenLabsUnavailable
from app.config import get_settings
from app.modules.negotiation import calls
from app.modules.negotiation.calls import dynamic_variables, load_call_context, start_call
from app.modules.threads import repo
from app.modules.threads.repo import claim_queued

pytestmark = pytest.mark.db

NOT_CONFIGURED = (
    "Calls aren't configured (ELEVENLABS_NEGOTIATION_AGENT_ID, ELEVENLABS_PHONE_NUMBER_ID)."
)


async def claim_arjun(api_db, launched_batch) -> UUID:
    """Claim the batch (Arjun's call thread goes to `calling`) and return his thread id."""
    async with api_db.acquire() as conn:
        await claim_queued(conn, limit=10, batch_id=launched_batch.batch_id)
    return launched_batch.threads["arjuntech"]


async def run(api_db, thread_id, *, elevenlabs, settings) -> None:
    await start_call(
        api_db,
        elevenlabs=elevenlabs,
        settings=settings,
        thread_id=thread_id,
        today=datetime.now(UTC).date(),
    )


async def thread_row(api_db, thread_id):
    async with api_db.acquire() as conn:
        return await conn.fetchrow(
            "select status, last_error, call_conversation_id from public.threads where id = $1",
            thread_id,
        )


async def events(api_db, thread_id, *types: str):
    """The thread's events of these types (all events when none are given), oldest first."""
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select type, actor, payload, external_id from public.thread_events"
            " where thread_id = $1 and (cardinality($2::text[]) = 0 or type = any($2::text[]))"
            " order by id",
            thread_id,
            list(types),
        )
    return [{**row, "payload": json.loads(row["payload"])} for row in rows]


async def phone_of(api_db, thread_id) -> str:
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select c.phone from public.threads t join public.creators c on c.id = t.creator_id"
            " where t.id = $1",
            thread_id,
        )


async def assert_failed(api_db, thread_id, reason: str) -> None:
    row = await thread_row(api_db, thread_id)
    assert row["status"] == "failed"
    assert row["last_error"] == reason
    assert [e["payload"] for e in await events(api_db, thread_id, "failed")] == [{"reason": reason}]


async def test_start_call_places_call_and_records_conversation(
    api_db, launched_batch, fake_elevenlabs, m2_settings
):
    thread_id = await claim_arjun(api_db, launched_batch)
    phone = await phone_of(api_db, thread_id)

    await run(api_db, thread_id, elevenlabs=fake_elevenlabs, settings=m2_settings)

    async with api_db.acquire() as conn:
        expected = dynamic_variables(await load_call_context(conn, thread_id))
    assert fake_elevenlabs.calls == [
        {
            "agent_id": "agent_neg",
            "phone_number_id": "phnum_1",
            "to_number": phone,
            "dynamic_variables": expected,
        }
    ]
    row = await thread_row(api_db, thread_id)
    assert row["status"] == "calling"
    assert row["call_conversation_id"] == "conv_1"
    (placed,) = await events(api_db, thread_id, "call_placed")
    assert placed["actor"] == "brand_agent"
    assert placed["external_id"] == "conv_1"
    assert placed["payload"] == {}
    assert phone not in json.dumps(await events(api_db, thread_id), default=str)


async def test_unconfigured_calls_fail_with_reason(api_db, launched_batch, fake_elevenlabs):
    thread_id = await claim_arjun(api_db, launched_batch)
    blank = get_settings().model_copy(
        update={"elevenlabs_negotiation_agent_id": "", "elevenlabs_phone_number_id": ""}
    )

    await run(api_db, thread_id, elevenlabs=fake_elevenlabs, settings=blank)

    assert fake_elevenlabs.calls == []
    await assert_failed(api_db, thread_id, NOT_CONFIGURED)


async def test_missing_elevenlabs_client_fails_with_reason(api_db, launched_batch, m2_settings):
    thread_id = await claim_arjun(api_db, launched_batch)

    await run(api_db, thread_id, elevenlabs=None, settings=m2_settings)

    await assert_failed(api_db, thread_id, NOT_CONFIGURED)


async def test_daily_call_cap(api_db, launched_batch, fake_elevenlabs, m2_settings, monkeypatch):
    thread_id = await claim_arjun(api_db, launched_batch)

    async def twenty(conn, brand_id, today):
        return 20

    monkeypatch.setattr(repo, "count_calls_today", twenty)

    await run(api_db, thread_id, elevenlabs=fake_elevenlabs, settings=m2_settings)

    assert fake_elevenlabs.calls == []
    await assert_failed(api_db, thread_id, "Daily call limit reached (20 calls).")


async def test_no_phone_opt_in_fails_without_calling(
    api_db, launched_batch, fake_elevenlabs, m2_settings, monkeypatch
):
    # Seeded creators are read-only in tests, so the guard is forced shut instead.
    thread_id = await claim_arjun(api_db, launched_batch)
    monkeypatch.setattr(calls, "call_allowed", lambda phone, phone_opt_in: False)

    await run(api_db, thread_id, elevenlabs=fake_elevenlabs, settings=m2_settings)

    assert fake_elevenlabs.calls == []
    await assert_failed(api_db, thread_id, "No phone opt-in.")


async def test_call_placement_failure_recorded(
    api_db, launched_batch, fake_elevenlabs, m2_settings
):
    thread_id = await claim_arjun(api_db, launched_batch)
    fake_elevenlabs.call_failure = CallPlacementFailed("invalid number")

    await run(api_db, thread_id, elevenlabs=fake_elevenlabs, settings=m2_settings)

    await assert_failed(api_db, thread_id, "Call couldn't be placed: invalid number")
    assert (await thread_row(api_db, thread_id))["call_conversation_id"] is None
    assert await events(api_db, thread_id, "call_placed") == []


async def test_placement_failure_never_leaks_the_phone_number(
    api_db, launched_batch, fake_elevenlabs, m2_settings
):
    thread_id = await claim_arjun(api_db, launched_batch)
    phone = await phone_of(api_db, thread_id)
    digits = phone.lstrip("+")
    fake_elevenlabs.call_failure = CallPlacementFailed(
        f"The number {phone} is unverified; also {digits}, ({digits}) and "
        f"{phone[:2]} {digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    )

    await run(api_db, thread_id, elevenlabs=fake_elevenlabs, settings=m2_settings)

    reason = "Call couldn't be placed: The number the creator's number is unverified; also "
    reason += "the creator's number, (the creator's number) and the creator's number"
    await assert_failed(api_db, thread_id, reason)
    row = await thread_row(api_db, thread_id)
    everything = json.dumps(await events(api_db, thread_id), default=str) + row["last_error"]
    assert digits not in everything


async def test_voice_service_unavailable_recorded(
    api_db, launched_batch, fake_elevenlabs, m2_settings
):
    thread_id = await claim_arjun(api_db, launched_batch)
    fake_elevenlabs.call_failure = ElevenLabsUnavailable("down")

    await run(api_db, thread_id, elevenlabs=fake_elevenlabs, settings=m2_settings)

    await assert_failed(api_db, thread_id, "Voice service unavailable. Retry to call again.")


async def test_count_calls_today_counts_call_placed_events_since_utc_midnight(
    api_db, launched_batch, fake_elevenlabs, m2_settings
):
    thread_id = await claim_arjun(api_db, launched_batch)
    today = datetime.now(UTC).date()
    async with api_db.acquire() as conn:
        brand_id = await conn.fetchval(
            "select brand_id from public.threads where id = $1", thread_id
        )
        before = await repo.count_calls_today(conn, brand_id, today)

    await run(api_db, thread_id, elevenlabs=fake_elevenlabs, settings=m2_settings)

    async with api_db.acquire() as conn:
        assert await repo.count_calls_today(conn, brand_id, today) == before + 1
        assert await repo.count_calls_today(conn, brand_id, today.replace(year=2999)) == 0

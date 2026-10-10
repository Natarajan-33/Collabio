"""CallWatcher: drives placed calls to the end by polling ElevenLabs."""

import json
from uuid import UUID

import pytest

from app.adapters.elevenlabs import ConversationSnapshot
from app.modules.threads import repo
from app.modules.threads.repo import claim_queued, transition
from app.schemas.negotiation import TranscriptTurn
from app.workers.call_watcher import CallWatcher

pytestmark = pytest.mark.db

NO_ANSWER = "No answer."


class Completions:
    """A `complete_call` that records what it was handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ConversationSnapshot]] = []

    async def __call__(self, conversation_id: str, snapshot: ConversationSnapshot) -> None:
        self.calls.append((conversation_id, snapshot))


def snapshot(conversation_id: str, status: str, *, user_spoke: bool = False):
    turns = [TranscriptTurn(role="agent", text="Hi, is now a good time?", t=0)]
    if user_spoke:
        turns.append(TranscriptTurn(role="user", text="Sure, go ahead.", t=4))
    return ConversationSnapshot(
        conversation_id=conversation_id,
        status=status,
        turns=turns,
        duration_secs=30,
        summary=None,
    )


async def calling_thread(api_db, launched_batch, conversation_id: str = "conv_w1") -> UUID:
    """Arjun's thread claimed to `calling` with a placed call."""
    thread_id = launched_batch.threads["arjuntech"]
    async with api_db.acquire() as conn:
        await claim_queued(conn, limit=10, batch_id=launched_batch.batch_id)
        await repo.set_call_conversation(conn, thread_id, conversation_id)
    return thread_id


async def thread_row(api_db, thread_id):
    async with api_db.acquire() as conn:
        return await conn.fetchrow(
            "select status, last_error from public.threads where id = $1", thread_id
        )


async def events(api_db, thread_id, *types: str):
    async with api_db.acquire() as conn:
        rows = await conn.fetch(
            "select type, actor, payload, external_id from public.thread_events"
            " where thread_id = $1 and type = any($2::text[]) order by id",
            thread_id,
            list(types),
        )
    return [{**row, "payload": json.loads(row["payload"])} for row in rows]


def watcher(api_db, fake_elevenlabs, completions) -> CallWatcher:
    return CallWatcher(api_db, fake_elevenlabs, complete_call=completions)


async def test_in_progress_marks_in_call(api_db, launched_batch, fake_elevenlabs):
    thread_id = await calling_thread(api_db, launched_batch)
    fake_elevenlabs.snapshots["conv_w1"] = snapshot("conv_w1", "in-progress")
    completions = Completions()

    await watcher(api_db, fake_elevenlabs, completions).check_once(batch_id=launched_batch.batch_id)

    assert (await thread_row(api_db, thread_id))["status"] == "in_call"
    (started,) = await events(api_db, thread_id, "call_started")
    assert started["external_id"] == "conv_w1"
    assert started["actor"] == "system"
    assert completions.calls == []


async def test_in_progress_again_changes_nothing(api_db, launched_batch, fake_elevenlabs):
    thread_id = await calling_thread(api_db, launched_batch)
    fake_elevenlabs.snapshots["conv_w1"] = snapshot("conv_w1", "in-progress")
    check = watcher(api_db, fake_elevenlabs, Completions())

    await check.check_once(batch_id=launched_batch.batch_id)
    await check.check_once(batch_id=launched_batch.batch_id)

    assert (await thread_row(api_db, thread_id))["status"] == "in_call"
    assert len(await events(api_db, thread_id, "call_started")) == 1


@pytest.mark.parametrize("status", ["done", "failed"])
async def test_unanswered_call_fails_with_retry(api_db, launched_batch, fake_elevenlabs, status):
    thread_id = await calling_thread(api_db, launched_batch)
    fake_elevenlabs.snapshots["conv_w1"] = snapshot("conv_w1", status, user_spoke=False)
    completions = Completions()

    await watcher(api_db, fake_elevenlabs, completions).check_once(batch_id=launched_batch.batch_id)

    row = await thread_row(api_db, thread_id)
    assert row["status"] == "failed"
    assert row["last_error"] == NO_ANSWER
    (failed,) = await events(api_db, thread_id, "failed")
    assert failed["payload"] == {"reason": NO_ANSWER}
    assert failed["external_id"] == "conv_w1"
    assert completions.calls == []


async def test_finished_call_handed_to_complete(api_db, launched_batch, fake_elevenlabs):
    thread_id = await calling_thread(api_db, launched_batch)
    await transition_to_in_call(api_db, thread_id)
    done = snapshot("conv_w1", "done", user_spoke=True)
    fake_elevenlabs.snapshots["conv_w1"] = done
    completions = Completions()

    await watcher(api_db, fake_elevenlabs, completions).check_once(batch_id=launched_batch.batch_id)

    assert completions.calls == [("conv_w1", done)]
    assert (await thread_row(api_db, thread_id))["status"] == "in_call"  # completion is Task 13


async def test_finished_call_with_speech_while_calling_is_completed(
    api_db, launched_batch, fake_elevenlabs
):
    await calling_thread(api_db, launched_batch)
    fake_elevenlabs.snapshots["conv_w1"] = snapshot("conv_w1", "done", user_spoke=True)
    completions = Completions()

    await watcher(api_db, fake_elevenlabs, completions).check_once(batch_id=launched_batch.batch_id)

    assert len(completions.calls) == 1


async def test_unanswered_call_already_in_call_is_completed_not_failed(
    api_db, launched_batch, fake_elevenlabs
):
    thread_id = await calling_thread(api_db, launched_batch)
    await transition_to_in_call(api_db, thread_id)
    fake_elevenlabs.snapshots["conv_w1"] = snapshot("conv_w1", "done", user_spoke=False)
    completions = Completions()

    await watcher(api_db, fake_elevenlabs, completions).check_once(batch_id=launched_batch.batch_id)

    assert len(completions.calls) == 1
    assert (await thread_row(api_db, thread_id))["status"] == "in_call"


@pytest.mark.parametrize("status", ["initiated", "processing"])
async def test_processing_waits(api_db, launched_batch, fake_elevenlabs, status):
    thread_id = await calling_thread(api_db, launched_batch)
    fake_elevenlabs.snapshots["conv_w1"] = snapshot("conv_w1", status)
    completions = Completions()

    await watcher(api_db, fake_elevenlabs, completions).check_once(batch_id=launched_batch.batch_id)

    assert (await thread_row(api_db, thread_id))["status"] == "calling"
    assert completions.calls == []
    assert await events(api_db, thread_id, "call_started", "failed") == []


async def test_lookup_error_skipped(api_db, launched_batch, fake_elevenlabs):
    thread_id = await calling_thread(api_db, launched_batch)  # no snapshot: lookup raises
    completions = Completions()

    await watcher(api_db, fake_elevenlabs, completions).check_once(batch_id=launched_batch.batch_id)

    assert (await thread_row(api_db, thread_id))["status"] == "calling"
    assert completions.calls == []


async def test_one_failing_row_does_not_stop_the_others(
    api_db, launched_batch, fake_elevenlabs, caplog
):
    thread_id = await calling_thread(api_db, launched_batch)
    fake_elevenlabs.snapshots["conv_w1"] = snapshot("conv_w1", "done", user_spoke=True)

    async def broken(conversation_id, snapshot):
        raise RuntimeError("boom")

    await CallWatcher(api_db, fake_elevenlabs, complete_call=broken).check_once(
        batch_id=launched_batch.batch_id
    )

    assert (await thread_row(api_db, thread_id))["status"] == "calling"
    assert "boom" in caplog.text


async def test_live_calls_lists_calling_and_in_call_with_a_conversation(api_db, launched_batch):
    thread_id = await calling_thread(api_db, launched_batch)

    async with api_db.acquire() as conn:
        live = await repo.live_calls(conn, batch_id=launched_batch.batch_id)

    assert [(c.thread.id, c.status, c.conversation_id) for c in live] == [
        (thread_id, "calling", "conv_w1")
    ]
    assert live[0].thread.batch_id == launched_batch.batch_id


async def test_live_calls_ignores_calling_threads_without_a_conversation(api_db, launched_batch):
    async with api_db.acquire() as conn:
        await claim_queued(conn, limit=10, batch_id=launched_batch.batch_id)
        assert await repo.live_calls(conn, batch_id=launched_batch.batch_id) == []


async def transition_to_in_call(api_db, thread_id) -> None:
    async with api_db.acquire() as conn:
        await transition(conn, thread_id, expected={"calling"}, target="in_call")

"""The FakeEmail / FakeElevenLabs contracts that later tasks' tests rely on."""

import pytest

from app.adapters.elevenlabs import (
    CallPlacementFailed,
    ConversationSnapshot,
    ElevenLabsUnavailable,
)
from app.adapters.email import OutboundEmail
from tests.fakes import FakeElevenLabs, FakeEmail


def make_email(to: str = "a@creators.io") -> OutboundEmail:
    return OutboundEmail(
        to=to, sender="b@mail.app", reply_to=None, subject="s", html="<p>h</p>", text="h"
    )


async def test_fake_email_dedupes_by_idempotency_key():
    fake = FakeEmail()
    first = await fake.send(make_email(), idempotency_key="k1")
    again = await fake.send(make_email(), idempotency_key="k1")
    other = await fake.send(make_email("b@creators.io"), idempotency_key="k2")
    assert (first, again, other) == ("email_1", "email_1", "email_2")
    assert [key for _, key in fake.sent] == ["k1", "k2"]


async def test_fake_email_failure_is_keyed_by_recipient_and_records_nothing():
    fake = FakeEmail()
    fake.failures["bad@creators.io"] = RuntimeError("rejected")
    with pytest.raises(RuntimeError, match="rejected"):
        await fake.send(make_email("bad@creators.io"), idempotency_key="k1")
    assert fake.sent == []
    assert await fake.send(make_email(), idempotency_key="k2") == "email_1"


async def test_fake_email_crash_after_send_records_the_send():
    fake = FakeEmail()
    fake.crash_after_send = True
    with pytest.raises(RuntimeError, match="crash"):
        await fake.send(make_email(), idempotency_key="k1")
    assert len(fake.sent) == 1
    fake.crash_after_send = False
    assert await fake.send(make_email(), idempotency_key="k1") == "email_1"
    assert len(fake.sent) == 1


async def test_fake_elevenlabs_calls_tokens_and_snapshots():
    fake = FakeElevenLabs()
    assert await fake.mint_conversation_token("agent_1")
    assert fake.conversation_tokens == ["agent_1"]

    kwargs = {
        "agent_id": "a",
        "phone_number_id": "p",
        "to_number": "+1",
        "dynamic_variables": {"x": "y"},
    }
    assert await fake.place_call(**kwargs) == "conv_1"
    assert await fake.place_call(**kwargs) == "conv_2"
    assert fake.calls[0] == kwargs

    fake.call_failure = CallPlacementFailed("no")
    with pytest.raises(CallPlacementFailed):
        await fake.place_call(**kwargs)

    fake.call_failure = None
    assert await fake.place_call(**kwargs) == "conv_3"  # the failed attempt used no id
    assert len(fake.calls) == 4  # but every attempt is recorded

    with pytest.raises(ElevenLabsUnavailable):
        await fake.get_conversation("conv_1")
    snapshot = ConversationSnapshot(
        conversation_id="conv_1", status="done", turns=[], duration_secs=None, summary=None
    )
    fake.snapshots["conv_1"] = snapshot
    assert await fake.get_conversation("conv_1") is snapshot

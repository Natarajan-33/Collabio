from uuid import uuid4

import pytest

from app.modules.briefs.launch import (
    ChannelNotAllowed,
    LaunchCandidate,
    PlannedThread,
    plan_launch,
)
from app.schemas.briefs import LaunchExclusion

PHONE = "+15551234567"


def candidate(
    preferred="email_first", *, phone=None, phone_opt_in=False, contact_opt_out=False
) -> LaunchCandidate:
    return LaunchCandidate(
        creator_id=uuid4(),
        package_id=uuid4(),
        preferred_channel=preferred,
        phone=phone,
        phone_opt_in=phone_opt_in,
        contact_opt_out=contact_opt_out,
    )


def test_plan_defaults_channels():
    caller = candidate("phone_ok", phone=PHONE, phone_opt_in=True)
    writer = candidate("email_first", phone=PHONE, phone_opt_in=True)

    planned, excluded = plan_launch([caller, writer], {})

    assert excluded == []
    assert planned == [
        PlannedThread(caller.creator_id, caller.package_id, "call"),
        PlannedThread(writer.creator_id, writer.package_id, "email"),
    ]


def test_plan_honours_explicit_email_for_phone_creator():
    caller = candidate("phone_ok", phone=PHONE, phone_opt_in=True)

    planned, _ = plan_launch([caller], {caller.creator_id: "email"})

    assert [p.channel_plan for p in planned] == ["email"]


def test_plan_rejects_call_without_opt_in():
    silent = candidate("email_first", phone=PHONE, phone_opt_in=False)

    with pytest.raises(ChannelNotAllowed) as caught:
        plan_launch([silent], {silent.creator_id: "call"})

    assert caught.value.creator_id == silent.creator_id
    assert caught.value.message == "No phone opt-in"


def test_plan_excludes_opted_out():
    opted_out = candidate(contact_opt_out=True)
    other = candidate()

    planned, excluded = plan_launch([opted_out, other], {opted_out.creator_id: "email"})

    assert excluded == [
        LaunchExclusion(creator_id=opted_out.creator_id, reason="Opted out of contact")
    ]
    assert [p.creator_id for p in planned] == [other.creator_id]

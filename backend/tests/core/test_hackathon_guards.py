"""Hackathon mode guards that need no database: caps, email-only launch and dispatch."""

from uuid import uuid4

import pytest

from app.core.caps import LIMITS, cap_for
from app.modules.briefs.launch import LaunchCandidate, plan_launch
from app.workers.orchestrator import handler_key

PHONE = "+15551234567"


def test_cap_for_known_kinds():
    assert LIMITS == {
        "settlement": 60,
        "agent_message": 80,
        "agent_call": 800,
        "agent_ktokens": 2000,
        "bonus_preview": 60,
        "voice_session": 15,
        "settlement_ip": 10,
        "bonus_preview_ip": 20,
    }
    assert cap_for("settlement") == 60
    with pytest.raises(KeyError):
        cap_for("nope")


def test_plan_launch_email_only_coerces_call_plans():
    caller = LaunchCandidate(
        creator_id=uuid4(),
        package_id=uuid4(),
        preferred_channel="phone_ok",
        phone=PHONE,
        phone_opt_in=True,
        contact_opt_out=False,
    )
    chosen = LaunchCandidate(
        creator_id=uuid4(),
        package_id=uuid4(),
        preferred_channel="phone_ok",
        phone=PHONE,
        phone_opt_in=True,
        contact_opt_out=False,
    )
    planned, _ = plan_launch(
        [caller, chosen], {chosen.creator_id: "email_then_call"}, email_only=True
    )
    assert [p.channel_plan for p in planned] == ["email", "email"]


def test_handler_key_email_only_never_calls():
    assert handler_key("call") == "call"
    assert handler_key("call", email_only=True) == "email"
    assert handler_key("email_then_call", email_only=True) == "email"


def test_email_only_launch_ignores_call_permission():
    no_phone = LaunchCandidate(
        creator_id=uuid4(),
        package_id=uuid4(),
        preferred_channel="email_first",
        phone=None,
        phone_opt_in=False,
        contact_opt_out=False,
    )
    planned, _ = plan_launch([no_phone], {no_phone.creator_id: "call"}, email_only=True)
    assert [p.channel_plan for p in planned] == ["email"]

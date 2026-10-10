"""snapshot_from_payload: a finished ElevenLabs conversation, reduced to what we store."""

from app.adapters.elevenlabs import ConversationSnapshot, snapshot_from_payload

RAW = {
    "conversation_id": "c1",
    "status": "done",
    "transcript": [
        {"role": "agent", "message": "Hi Arjun", "time_in_call_secs": 0},
        {
            "role": "agent",
            "message": None,
            "time_in_call_secs": 5,
            "tool_calls": [{"tool_name": "check_counter"}],
            "tool_results": [{"result_value": '{"suggested_counter_price_usd": 1100}'}],
        },
        {"role": "user", "message": " three for thirteen hundred ", "time_in_call_secs": 7},
    ],
    "metadata": {"call_duration_secs": 95},
    "analysis": {"transcript_summary": "Countered at $1,300."},
}


def test_turns_drop_tool_traffic():
    s = snapshot_from_payload(RAW)
    assert [t.model_dump() for t in s.turns] == [
        {"role": "agent", "text": "Hi Arjun", "t": 0.0},
        {"role": "user", "text": "three for thirteen hundred", "t": 7.0},
    ]
    assert "1100" not in s.model_dump_json()
    assert "check_counter" not in s.model_dump_json()


def test_tool_text_on_a_spoken_turn_is_not_kept():
    raw = {
        **RAW,
        "transcript": [
            {
                "role": "agent",
                "message": "Let me check",
                "time_in_call_secs": 1,
                "tool_calls": [{"tool_name": "check_counter"}],
                "tool_results": [{"result_value": "1100"}],
            }
        ],
    }
    s = snapshot_from_payload(raw)
    assert [t.text for t in s.turns] == ["Let me check"]
    assert "1100" not in s.model_dump_json()


def test_blank_messages_are_dropped():
    raw = {
        **RAW,
        "transcript": [
            {"role": "user", "message": "   ", "time_in_call_secs": 1},
            {"role": "agent", "message": "", "time_in_call_secs": 2},
        ],
    }
    assert snapshot_from_payload(raw).turns == []


def test_user_spoke():
    agent_only = {
        **RAW,
        "transcript": [{"role": "agent", "message": "Hello?", "time_in_call_secs": 0}],
    }
    assert snapshot_from_payload(agent_only).user_spoke is False
    assert snapshot_from_payload(RAW).user_spoke is True


def test_a_blank_user_turn_is_not_speech():
    raw = {**RAW, "transcript": [{"role": "user", "message": " ", "time_in_call_secs": 3}]}
    assert snapshot_from_payload(raw).user_spoke is False


def test_duration_and_summary():
    s = snapshot_from_payload(RAW)
    assert isinstance(s, ConversationSnapshot)
    assert (s.conversation_id, s.status) == ("c1", "done")
    assert s.duration_secs == 95
    assert s.summary == "Countered at $1,300."


def test_missing_metadata_and_analysis_are_none():
    s = snapshot_from_payload({"conversation_id": "c2", "status": "initiated", "transcript": []})
    assert s.duration_secs is None
    assert s.summary is None
    assert s.turns == []

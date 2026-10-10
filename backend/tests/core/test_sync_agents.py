"""The agent sync script against a mocked ElevenLabs REST API (respx); no live calls."""

import json
import shutil

import httpx
import pytest

from scripts.sync_agents import (
    AGENTS_DIR,
    BASE_URL,
    check_backend_url,
    check_voices,
    dry_run,
    main,
    print_phone_numbers,
    substitute,
    sync,
)

SECRET = "s3cret-tool-value"
VALUES = {
    "PUBLIC_BACKEND_URL": "https://collabio.example",
    "ELEVENLABS_TOOL_SECRET": SECRET,
    "ELEVENLABS_BRIEF_VOICE_ID": "voice_brief",
    "ELEVENLABS_NEGOTIATION_VOICE_ID": "voice_neg",
}
TOOLS = ("check_counter", "log_offer", "update_brief", "show_creator", "ready_to_launch")


@pytest.fixture
def agents_dir(tmp_path):
    target = tmp_path / "agents"
    shutil.copytree(AGENTS_DIR, target)
    return target


@pytest.fixture
async def http():
    async with httpx.AsyncClient(base_url=BASE_URL, headers={"xi-api-key": "k"}) as client:
        yield client


def mock_tools(respx_mock, existing: list[dict] | None = None):
    """GET lists `existing`; POSTs answer with a new id per tool; PATCHes answer 200."""
    respx_mock.get("/v1/convai/tools").mock(
        return_value=httpx.Response(200, json={"tools": existing or []})
    )
    ids = iter(f"tool_new_{n}" for n in range(10))
    posted = respx_mock.post("/v1/convai/tools").mock(
        side_effect=lambda request: httpx.Response(200, json={"id": next(ids)})
    )
    return posted


def body(call) -> dict:
    return json.loads(call.request.content)


def test_substitute_replaces_and_reports_missing():
    obj = {"url": "${A}/x", "list": ["${B}", 3, None], "nested": {"k": "plain ${A}${B}"}}
    assert substitute(obj, {"A": "1", "B": "2"}) == {
        "url": "1/x",
        "list": ["2", 3, None],
        "nested": {"k": "plain 12"},
    }
    with pytest.raises(KeyError, match="NOPE"):
        substitute({"x": ["${NOPE}"]}, {"A": "1"})


def test_substitute_leaves_dynamic_variables_alone():
    assert substitute("Hi {{name}} at $5", {}) == "Hi {{name}} at $5"


async def test_tools_patched_not_duplicated(respx_mock, http, agents_dir):
    existing = [{"id": "tool_1", "tool_config": {"name": "check_counter"}}]
    posted = mock_tools(respx_mock, existing)
    patched = respx_mock.patch("/v1/convai/tools/tool_1").mock(
        return_value=httpx.Response(200, json={"id": "tool_1"})
    )
    respx_mock.post("/v1/convai/agents/create").mock(
        return_value=httpx.Response(200, json={"agent_id": "agent_x"})
    )

    await sync(http, agents_dir=agents_dir, values=VALUES, agent_ids={})

    assert patched.call_count == 1
    assert body(patched.calls[0])["tool_config"]["name"] == "check_counter"
    created = {body(call)["tool_config"]["name"] for call in posted.calls}
    assert created == set(TOOLS) - {"check_counter"}


async def test_tool_secret_and_url_are_substituted(respx_mock, http, agents_dir):
    posted = mock_tools(respx_mock)
    respx_mock.post("/v1/convai/agents/create").mock(
        return_value=httpx.Response(200, json={"agent_id": "agent_x"})
    )

    await sync(http, agents_dir=agents_dir, values=VALUES, agent_ids={})

    check = next(
        body(c) for c in posted.calls if body(c)["tool_config"]["name"] == "check_counter"
    )["tool_config"]["api_schema"]
    assert check["url"] == "https://collabio.example/api/v1/webhooks/elevenlabs/tools/check-counter"
    assert check["request_headers"] == {"X-Collabio-Tool-Secret": SECRET}


async def test_tool_names_become_tool_ids(respx_mock, http, agents_dir):
    mock_tools(respx_mock)
    created = respx_mock.post("/v1/convai/agents/create").mock(
        return_value=httpx.Response(200, json={"agent_id": "agent_x"})
    )

    await sync(http, agents_dir=agents_dir, values=VALUES, agent_ids={})

    bodies = {body(c)["name"]: body(c) for c in created.calls}
    brief = bodies["Collabio Brief Agent"]
    negotiation = bodies["Collabio Negotiation Agent"]
    assert "tool_names" not in brief and "tool_names" not in negotiation
    assert len(brief["conversation_config"]["agent"]["prompt"]["tool_ids"]) == 3
    assert len(negotiation["conversation_config"]["agent"]["prompt"]["tool_ids"]) == 2
    assert brief["conversation_config"]["tts"]["voice_id"] == "voice_brief"
    assert negotiation["conversation_config"]["tts"]["voice_id"] == "voice_neg"
    assert set(brief["conversation_config"]["agent"]["prompt"]["tool_ids"]) <= {
        f"tool_new_{n}" for n in range(5)
    }


async def test_agent_created_when_unset_prints_env_line(respx_mock, http, agents_dir, capsys):
    mock_tools(respx_mock)
    respx_mock.post("/v1/convai/agents/create").mock(
        return_value=httpx.Response(200, json={"agent_id": "agent_x"})
    )

    ids = await sync(http, agents_dir=agents_dir, values=VALUES, agent_ids={})

    assert ids == {"brief_agent": "agent_x", "negotiation_agent": "agent_x"}
    out = capsys.readouterr().out
    assert "Set ELEVENLABS_NEGOTIATION_AGENT_ID=agent_x in backend/.env" in out
    assert "Set ELEVENLABS_BRIEF_AGENT_ID=agent_x in backend/.env" in out
    assert SECRET not in out


async def test_agent_patched_when_set(respx_mock, http, agents_dir, capsys):
    mock_tools(respx_mock)
    patched = respx_mock.patch("/v1/convai/agents/agent_x").mock(
        return_value=httpx.Response(200, json={"agent_id": "agent_x"})
    )
    created = respx_mock.post("/v1/convai/agents/create").mock(
        return_value=httpx.Response(200, json={"agent_id": "agent_b"})
    )

    ids = await sync(
        http,
        agents_dir=agents_dir,
        values=VALUES,
        agent_ids={"negotiation_agent": "agent_x"},
    )

    assert ids == {"brief_agent": "agent_b", "negotiation_agent": "agent_x"}
    assert patched.call_count == 1
    assert body(patched.calls[0])["name"] == "Collabio Negotiation Agent"
    assert created.call_count == 1
    out = capsys.readouterr().out
    assert "ELEVENLABS_NEGOTIATION_AGENT_ID" not in out


async def test_api_error_names_the_call_but_not_the_secret(respx_mock, http, agents_dir):
    respx_mock.get("/v1/convai/tools").mock(return_value=httpx.Response(401, json={}))

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await sync(http, agents_dir=agents_dir, values=VALUES, agent_ids={})

    assert SECRET not in str(raised.value)


def test_dry_run_masks_secret(capsys, respx_mock):
    dry_run(agents_dir=AGENTS_DIR, values=VALUES)

    out = capsys.readouterr().out
    assert "***" in out
    assert SECRET not in out
    assert "check_counter" in out and "Collabio Brief Agent" in out
    assert "https://collabio.example/api/v1/webhooks/elevenlabs/tools/check-counter" in out
    assert len(respx_mock.calls) == 0


def test_cli_dry_run_prints_no_secret_and_makes_no_request(capsys, monkeypatch, respx_mock):
    monkeypatch.setenv("ELEVENLABS_TOOL_SECRET", "env-tool-secret")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env-api-key")

    assert main(["--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "***" in out
    assert "env-tool-secret" not in out and "env-api-key" not in out
    assert len(respx_mock.calls) == 0


@pytest.mark.parametrize("url", ["http://localhost:8000", "", "ftp://x"])
def test_requires_https_backend_url(url):
    with pytest.raises(SystemExit, match="https://"):
        check_backend_url(url)


def test_https_backend_url_is_accepted():
    check_backend_url("https://collabio.example")


async def test_missing_voice_exits_with_a_message(respx_mock, http):
    respx_mock.get("/v1/voices/voice_ok").mock(return_value=httpx.Response(200, json={}))
    respx_mock.get("/v1/voices/voice_gone").mock(return_value=httpx.Response(404, json={}))

    await check_voices(http, {"ELEVENLABS_BRIEF_VOICE_ID": "voice_ok"})
    with pytest.raises(SystemExit, match="ELEVENLABS_NEGOTIATION_VOICE_ID.*voice_gone"):
        await check_voices(http, {"ELEVENLABS_NEGOTIATION_VOICE_ID": "voice_gone"})


async def test_phone_numbers_are_listed(respx_mock, http, capsys):
    respx_mock.get("/v1/convai/phone-numbers").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"phone_number_id": "phnum_1", "phone_number": "+15555550100", "label": "Main"},
                {"phone_number_id": "phnum_2", "phone_number": "+15555550101", "label": "Spare"},
            ],
        )
    )

    await print_phone_numbers(http)

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "phnum_1  +15555550100  Main"
    assert out[1] == "phnum_2  +15555550101  Spare"
    assert out[-1] == "Set ELEVENLABS_PHONE_NUMBER_ID to the outbound-capable one."

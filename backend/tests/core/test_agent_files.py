"""The agent and tool JSON under backend/agents/: what is sent to ElevenLabs, checked as files."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.sync_agents import AGENTS_DIR, substitute

AGENT_STEMS = ("brief_agent", "negotiation_agent")
FIRST_MESSAGE = (
    "Hi {{creator_first_name}}, this is an AI assistant calling on behalf of {{brand_name}}. "
    "This call is recorded for both parties' records — is now a good time?"
)
PLACEHOLDERS = {
    "PUBLIC_BACKEND_URL": "https://collabio.example",
    "ELEVENLABS_TOOL_SECRET": "s3cret",
    "ELEVENLABS_BRIEF_VOICE_ID": "voice_brief",
    "ELEVENLABS_NEGOTIATION_VOICE_ID": "voice_neg",
}


def load(name: str) -> dict[str, Any]:
    return json.loads((AGENTS_DIR / name).read_text(encoding="utf-8"))


def strings(node: Any):
    """Every string in a JSON value, and every key of every object in it."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from strings(item)


@pytest.mark.parametrize("stem", AGENT_STEMS)
def test_agent_files_reference_known_tools(stem):
    agent = load(f"{stem}.json")
    assert agent["tool_names"]
    for name in agent["tool_names"]:
        tool = load(f"tools/{name}.json")
        assert tool["tool_config"]["name"] == name


def test_every_tool_file_is_used_by_an_agent():
    used = {n for stem in AGENT_STEMS for n in load(f"{stem}.json")["tool_names"]}
    on_disk = {p.stem for p in (AGENTS_DIR / "tools").glob("*.json")}
    assert on_disk == used


def test_negotiation_first_message_is_spec_copy():
    agent = load("negotiation_agent.json")
    assert agent["conversation_config"]["agent"]["first_message"] == FIRST_MESSAGE


def test_negotiation_agent_has_no_ceiling_variable():
    agent = load("negotiation_agent.json")
    for text in strings(agent):
        for variable in re.findall(r"\{\{(.*?)\}\}", text):
            assert "ceiling" not in variable.lower()
    placeholders = agent["conversation_config"]["agent"]["dynamic_variables"]
    assert not [k for k in placeholders["dynamic_variable_placeholders"] if "ceiling" in k.lower()]
    assert "ceiling_cents" not in json.dumps(agent)
    assert "budget_ceiling" not in json.dumps(agent)


@pytest.mark.parametrize("stem", AGENT_STEMS)
def test_every_prompt_variable_has_a_placeholder_value(stem):
    config = load(f"{stem}.json")["conversation_config"]["agent"]
    declared = set(config["dynamic_variables"]["dynamic_variable_placeholders"])
    used = set(re.findall(r"\{\{(\w+)\}\}", config["first_message"] + config["prompt"]["prompt"]))
    assert used <= declared


def test_brief_agent_variables_match_the_voice_session():
    config = load("brief_agent.json")["conversation_config"]["agent"]
    assert set(config["dynamic_variables"]["dynamic_variable_placeholders"]) == {
        "brief_id",
        "brand_name",
        "product_name",
        "product_summary",
        "contact_email",
        "selected_creators_summary",
        "current_brief_json",
        "missing_fields",
        "today",
    }


@pytest.mark.parametrize("path", sorted(Path(AGENTS_DIR).rglob("*.json")), ids=lambda p: p.name)
def test_every_placeholder_is_one_the_script_substitutes(path):
    result = substitute(json.loads(path.read_text(encoding="utf-8")), PLACEHOLDERS)
    assert "${" not in json.dumps(result)

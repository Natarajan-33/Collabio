"""Pushes the ElevenLabs agents and their tools from `backend/agents/` to ElevenLabs.

    uv run python -m scripts.sync_agents [--dry-run]

The JSON under `backend/agents/` is exactly what is sent: each tool file is the body of
`POST /v1/convai/tools`, each agent file the body of `POST /v1/convai/agents/create` plus
one custom key, `tool_names`, which becomes `conversation_config.agent.prompt.tool_ids`.
`${NAME}` placeholders are filled in from backend/.env at sync time.

Tools are matched by name (patched when they exist, created otherwise). An agent is patched
when its id is set in backend/.env and created otherwise, in which case the script prints
the line to add. `--dry-run` prints what would be sent, with the tool secret masked, and
makes no request.
"""

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import ENV_FILE

BASE_URL = "https://api.elevenlabs.io"
AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
HTTP_TIMEOUT_SECONDS = 30.0

SECRET_KEYS = ("ELEVENLABS_TOOL_SECRET",)
MASK = "***"
PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")

# Agent file stem -> the env variable that holds its id.
AGENT_ID_VARS = {
    "brief_agent": "ELEVENLABS_BRIEF_AGENT_ID",
    "negotiation_agent": "ELEVENLABS_NEGOTIATION_AGENT_ID",
}
VOICE_VARS = ("ELEVENLABS_BRIEF_VOICE_ID", "ELEVENLABS_NEGOTIATION_VOICE_ID")


class SyncSettings(BaseSettings):
    """The sync script's slice of backend/.env. The voice ids are read here only: the app
    never uses them."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    elevenlabs_api_key: str = Field("", repr=False)
    elevenlabs_tool_secret: str = Field("", repr=False)
    elevenlabs_brief_agent_id: str = ""
    elevenlabs_negotiation_agent_id: str = ""
    elevenlabs_brief_voice_id: str = "EXAVITQu4vr4xnSDxMaL"
    elevenlabs_negotiation_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    public_backend_url: str = "http://localhost:8000"

    @property
    def values(self) -> dict[str, str]:
        """The `${NAME}` placeholder values."""
        return {
            "PUBLIC_BACKEND_URL": self.public_backend_url.rstrip("/"),
            "ELEVENLABS_TOOL_SECRET": self.elevenlabs_tool_secret,
            "ELEVENLABS_BRIEF_VOICE_ID": self.elevenlabs_brief_voice_id,
            "ELEVENLABS_NEGOTIATION_VOICE_ID": self.elevenlabs_negotiation_voice_id,
        }

    @property
    def agent_ids(self) -> dict[str, str]:
        return {
            "brief_agent": self.elevenlabs_brief_agent_id,
            "negotiation_agent": self.elevenlabs_negotiation_agent_id,
        }


def substitute(obj: Any, values: Mapping[str, str]) -> Any:
    """`obj` with every `${NAME}` in its strings replaced; raises `KeyError(NAME)` for a
    placeholder `values` does not have."""
    if isinstance(obj, str):
        return PLACEHOLDER.sub(lambda m: values[m.group(1)], obj)
    if isinstance(obj, dict):
        return {key: substitute(value, values) for key, value in obj.items()}
    if isinstance(obj, list):
        return [substitute(item, values) for item in obj]
    return obj


def check_backend_url(url: str) -> None:
    """ElevenLabs only calls tool webhooks over HTTPS; exits with a message otherwise."""
    if not url.startswith("https://"):
        raise SystemExit(
            f"PUBLIC_BACKEND_URL must start with https:// (got {url!r}): ElevenLabs cannot "
            "call a tool at a local or plain-HTTP address. Use a tunnel such as ngrok."
        )


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tool_files(agents_dir: Path) -> list[Path]:
    return sorted((agents_dir / "tools").glob("*.json"))


def _agent_files(agents_dir: Path) -> list[Path]:
    return sorted(agents_dir.glob("*.json"))


def masked(values: Mapping[str, str]) -> dict[str, str]:
    return {key: MASK if key in SECRET_KEYS else value for key, value in values.items()}


def dry_run(*, agents_dir: Path, values: Mapping[str, str]) -> None:
    """Print what a sync would send, with the secret masked; makes no request."""
    safe = masked(values)
    for path in _tool_files(agents_dir):
        print(f"TOOL {path.stem}")
        print(json.dumps(substitute(_load(path), safe), indent=2, ensure_ascii=False))
    for path in _agent_files(agents_dir):
        print(f"AGENT {path.stem}")
        print(json.dumps(substitute(_load(path), safe), indent=2, ensure_ascii=False))


async def check_voices(http: httpx.AsyncClient, voices: Mapping[str, str]) -> None:
    """Exit with a message when a configured voice does not exist for this account."""
    for var, voice_id in voices.items():
        response = await http.get(f"/v1/voices/{voice_id}")
        if response.status_code == httpx.codes.NOT_FOUND:
            raise SystemExit(f"{var}={voice_id} is not a voice in this ElevenLabs account.")
        response.raise_for_status()


async def _existing_tool_ids(http: httpx.AsyncClient) -> dict[str, str]:
    """Tool name -> id for every tool in the workspace."""
    ids: dict[str, str] = {}
    cursor: str | None = None
    while True:
        response = await http.get("/v1/convai/tools", params={"cursor": cursor} if cursor else None)
        response.raise_for_status()
        data = response.json()
        for tool in data["tools"]:
            ids[tool["tool_config"]["name"]] = tool["id"]
        cursor = data.get("next_cursor")
        if not (data.get("has_more") and cursor):
            return ids


async def _sync_tools(
    http: httpx.AsyncClient, agents_dir: Path, values: Mapping[str, str]
) -> dict[str, str]:
    """Create or patch every tool; tool name -> id."""
    ids = await _existing_tool_ids(http)
    for path in _tool_files(agents_dir):
        payload = substitute(_load(path), values)
        name = payload["tool_config"]["name"]
        if name in ids:
            response = await http.patch(f"/v1/convai/tools/{ids[name]}", json=payload)
            response.raise_for_status()
            print(f"tool {name}: updated")
        else:
            response = await http.post("/v1/convai/tools", json=payload)
            response.raise_for_status()
            ids[name] = response.json()["id"]
            print(f"tool {name}: created")
    return ids


async def sync(
    http: httpx.AsyncClient,
    *,
    agents_dir: Path,
    values: Mapping[str, str],
    agent_ids: Mapping[str, str],
) -> dict[str, str]:
    """Push the tools, then the agents; returns agent file stem -> agent id.

    An agent whose stem has an id in `agent_ids` is patched; any other is created and the
    line to put in backend/.env is printed.
    """
    tool_ids = await _sync_tools(http, agents_dir, values)
    result: dict[str, str] = {}
    for path in _agent_files(agents_dir):
        stem = path.stem
        payload = substitute(_load(path), values)
        names = payload.pop("tool_names")
        payload["conversation_config"]["agent"]["prompt"]["tool_ids"] = [
            tool_ids[name] for name in names
        ]
        existing = agent_ids.get(stem)
        if existing:
            response = await http.patch(f"/v1/convai/agents/{existing}", json=payload)
            response.raise_for_status()
            result[stem] = existing
            print(f"agent {stem}: updated")
        else:
            response = await http.post("/v1/convai/agents/create", json=payload)
            response.raise_for_status()
            result[stem] = response.json()["agent_id"]
            print(f"agent {stem}: created")
            print(f"Set {AGENT_ID_VARS[stem]}={result[stem]} in backend/.env")
    return result


async def print_phone_numbers(http: httpx.AsyncClient) -> None:
    """List the account's phone numbers, to pick the outbound-capable one."""
    response = await http.get("/v1/convai/phone-numbers")
    response.raise_for_status()
    for number in response.json():
        print(f"{number['phone_number_id']}  {number['phone_number']}  {number.get('label', '')}")
    print("Set ELEVENLABS_PHONE_NUMBER_ID to the outbound-capable one.")


async def run(settings: SyncSettings) -> None:
    values = settings.values
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"xi-api-key": settings.elevenlabs_api_key},
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as http:
        await check_voices(http, {var: values[var] for var in VOICE_VARS})
        await sync(http, agents_dir=AGENTS_DIR, values=values, agent_ids=settings.agent_ids)
        await print_phone_numbers(http)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.sync_agents",
        description="Create or update the ElevenLabs agents and tools from backend/agents/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be sent (secrets masked) and make no request",
    )
    args = parser.parse_args(argv)

    settings = SyncSettings()
    if args.dry_run:
        dry_run(agents_dir=AGENTS_DIR, values=settings.values)
        return 0
    if not settings.elevenlabs_api_key:
        print("Cannot sync: set ELEVENLABS_API_KEY in backend/.env first.", file=sys.stderr)
        return 1
    if not settings.elevenlabs_tool_secret:
        print("Cannot sync: set ELEVENLABS_TOOL_SECRET in backend/.env first.", file=sys.stderr)
        return 1
    check_backend_url(settings.public_backend_url)
    try:
        asyncio.run(run(settings))
    except httpx.HTTPStatusError as exc:
        # The message names the call and status only; request headers hold the API key.
        print(
            f"ElevenLabs refused {exc.request.method} {exc.request.url.path}: "
            f"{exc.response.status_code}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

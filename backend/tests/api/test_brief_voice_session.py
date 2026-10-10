"""POST /briefs/{id}/voice-session: a conversation token and the brief agent's variables."""

import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from app.adapters.elevenlabs import ElevenLabsUnavailable
from app.api.deps import get_elevenlabs
from app.config import get_settings
from app.modules.briefs.voice_session import brief_dynamic_variables
from app.schemas.briefs import DealBrief
from tests.fakes import FakeElevenLabs

pytestmark = pytest.mark.db

BASE = "/api/v1/briefs"
VARIABLES = {
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


async def new_brief(client, cleanup: list[str], *creator_ids) -> str:
    r = await client.post(BASE, json={"creator_ids": [str(i) for i in creator_ids]})
    assert r.status_code == 201, r.text
    cleanup.append(r.json()["id"])
    return r.json()["id"]


def make_brief(**overrides) -> DealBrief:
    fields = {
        "id": uuid4(),
        "status": "draft",
        "creator_ids": [],
        "approved_at": None,
        "batch_id": None,
        "missing": [],
        "violations": [],
        "brand_name": "Lumen Audio",
        "product_name": "Lumen Pods",
    }
    return DealBrief(**(fields | overrides))


def test_variables_for_a_partial_brief():
    brief = make_brief(deliverables_count=3, budget_ceiling_cents=150000)

    variables = brief_dynamic_variables(
        brief,
        [("Arjun Mehta", "2 videos/contract · $1,000"), ("Priya Rao", "1 video/week · $500")],
        date(2026, 10, 10),
    )

    assert set(variables) == VARIABLES
    assert all(isinstance(v, str) for v in variables.values())
    assert variables["brief_id"] == str(brief.id)
    assert variables["today"] == "2026-10-10"
    assert variables["selected_creators_summary"] == (
        "Arjun Mehta — 2 videos/contract · $1,000; Priya Rao — 1 video/week · $500"
    )
    assert json.loads(variables["current_brief_json"]) == {
        "brand_name": "Lumen Audio",
        "product_name": "Lumen Pods",
        "deliverables_count": 3,
        "budget_ceiling_cents": 150000,
        "flexibility": [],
    }
    assert variables["missing_fields"].startswith("product summary, deliverable format")
    assert "number of deliverables" not in variables["missing_fields"]


def test_nothing_missing_reads_nothing():
    brief = make_brief(
        product_summary="Earbuds",
        deliverables_count=1,
        deliverables_format="story",
        go_live_by=date(2026, 12, 1),
        budget_ceiling_cents=2000,
        ask_price_cents=1000,
        negotiation_ask="One story",
        flexibility=["price"],
        contact_email="a@b.co",
    )

    variables = brief_dynamic_variables(brief, [], date(2026, 10, 10))

    assert variables["missing_fields"] == "nothing"
    assert variables["selected_creators_summary"] == ""


async def test_voice_session_returns_token_and_variables(
    brand_client, m2_settings, fake_elevenlabs, brief_cleanup, seeded_ids
):
    brief_id = await new_brief(
        brand_client, brief_cleanup, seeded_ids["arjun"], seeded_ids["priya"]
    )

    r = await brand_client.post(f"{BASE}/{brief_id}/voice-session")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversation_token"] == "fake-conversation-token-1"
    assert fake_elevenlabs.conversation_tokens == ["agent_brief"]
    variables = body["dynamic_variables"]
    assert set(variables) == VARIABLES
    assert variables["brief_id"] == brief_id
    assert variables["brand_name"] == "Lumen Audio"
    assert variables["product_name"] == "Lumen Pods"
    assert "Arjun Mehta — " in variables["selected_creators_summary"]
    assert "Priya" in variables["selected_creators_summary"]
    assert variables["missing_fields"].startswith("number of deliverables")
    current = json.loads(variables["current_brief_json"])
    assert current["brand_name"] == "Lumen Audio"
    assert "deliverables_count" not in current
    assert variables["today"] == datetime.now(UTC).date().isoformat()


async def test_voice_session_503_without_agent(
    app, brand_client, m2_settings, fake_elevenlabs, brief_cleanup, seeded_ids
):
    # Blank on purpose: backend/.env holds the real agent id once the agents are synced.
    blank = m2_settings.model_copy(update={"elevenlabs_brief_agent_id": ""})
    app.dependency_overrides[get_settings] = lambda: blank
    brief_id = await new_brief(brand_client, brief_cleanup, seeded_ids["priya"])

    r = await brand_client.post(f"{BASE}/{brief_id}/voice-session")

    assert r.status_code == 503
    assert r.json()["detail"] == "voice_unavailable"
    assert fake_elevenlabs.conversation_tokens == []


async def test_voice_session_503_when_elevenlabs_fails(
    app, brand_client, m2_settings, brief_cleanup, seeded_ids
):
    class Down(FakeElevenLabs):
        async def mint_conversation_token(self, agent_id: str) -> str:
            raise ElevenLabsUnavailable("down")

    app.dependency_overrides[get_elevenlabs] = lambda: Down()
    brief_id = await new_brief(brand_client, brief_cleanup, seeded_ids["priya"])

    r = await brand_client.post(f"{BASE}/{brief_id}/voice-session")

    assert r.status_code == 503
    assert r.json()["detail"] == "voice_unavailable"


async def test_voice_session_409_after_launch(
    brand_client, m2_settings, api_db, brief_cleanup, seeded_ids
):
    brief_id = await new_brief(brand_client, brief_cleanup, seeded_ids["priya"])
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.briefs set status = 'launched', approved_at = now() where id = $1",
            UUID(brief_id),
        )

    r = await brand_client.post(f"{BASE}/{brief_id}/voice-session")

    assert r.status_code == 409
    assert r.json()["detail"] == "brief_launched"


async def test_voice_session_other_brand_404(
    brand_client, new_brand_client, m2_settings, brief_cleanup, seeded_ids
):
    brief_id = await new_brief(brand_client, brief_cleanup, seeded_ids["priya"])

    r = await new_brand_client.post(f"{BASE}/{brief_id}/voice-session")

    assert r.status_code == 404
    assert r.json()["detail"] == "brief_not_found"

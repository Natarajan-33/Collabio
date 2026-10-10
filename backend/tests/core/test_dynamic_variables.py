"""The negotiation agent's dynamic variables: exactly what it may know, and never the ceiling."""

import json
from datetime import date
from uuid import uuid4

import pytest

from app.modules.negotiation.calls import CallContext, dynamic_variables, load_call_context
from app.modules.threads.repo import ThreadRef
from app.schemas.packages import PackageTerms

PACKAGE = PackageTerms(
    name="Launch Pack",
    content_type="short_video",
    niche="consumer_tech",
    volume_count=2,
    volume_basis="per_contract",
    base_price_cents=80000,
    preferred_channel="phone_ok",
)


def make_context(**overrides) -> CallContext:
    fields = {
        "thread": ThreadRef(id=uuid4(), batch_id=uuid4(), brand_id=uuid4(), creator_id=uuid4()),
        "brand_name": "Lumen Audio",
        "product_summary": "Open-ear earbuds",
        "creator_name": "Arjun Mehta",
        "phone": "+15555550123",
        "phone_opt_in": True,
        "package_name": "Launch Pack",
        "package": PACKAGE,
        "ask_videos": 3,
        "ask_price_cents": 100000,
        "go_live_by": date(2026, 11, 14),
        "flexibility": ["timeline", "usage"],
    }
    return CallContext(**(fields | overrides))


def test_dynamic_variables_exact():
    ctx = make_context()
    variables = dynamic_variables(ctx)

    assert variables == {
        "thread_id": str(ctx.thread.id),
        "creator_first_name": "Arjun",
        "brand_name": "Lumen Audio",
        "product_summary": "Open-ear earbuds",
        "package_name": "Launch Pack",
        "package_terms": "2 videos/contract · $800",
        "ask_videos": "3",
        "ask_price": "$1,000",
        "go_live_by": "November 14, 2026",
        "flexibility": "timeline, usage",
        "follow_up_context": "",
    }
    assert len(variables) == 11


def test_dynamic_variables_thread_id_and_empty_flexibility():
    ctx = make_context(flexibility=[])
    variables = dynamic_variables(ctx)

    assert variables["thread_id"] == str(ctx.thread.id)
    assert variables["flexibility"] == "none"


@pytest.mark.db
async def test_dynamic_variables_exclude_ceiling(api_db, launched_batch):
    async with api_db.acquire() as conn:
        ctx = await load_call_context(conn, launched_batch.threads["arjuntech"])
        ceiling = await conn.fetchval(
            "select budget_ceiling_cents from public.briefs where id = $1", launched_batch.brief_id
        )
    assert ceiling == 123400

    variables = dynamic_variables(ctx)

    assert ctx.creator_name.split()[0] == variables["creator_first_name"]
    blob = json.dumps(variables)
    for needle in ("1,234", "123400", "1234"):
        assert needle not in blob
    assert not any(field == "budget_ceiling_cents" for field in vars(ctx))

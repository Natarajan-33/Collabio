"""The briefs API: /briefs create, read, patch and preview.

`brand_client` is the seeded Lumen Audio and `new_brand_client` a throwaway second brand.
The tests share the hosted database, so every brief they create goes into `brief_cleanup`.
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.config import get_settings
from scripts.seed import DEMO_PRODUCT_SUMMARY

pytestmark = pytest.mark.db

BASE = "/api/v1/briefs"


def go_live(days: int = 30) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


async def create(client, cleanup: list[str], *creator_ids: UUID) -> dict:
    r = await client.post(BASE, json={"creator_ids": [str(i) for i in creator_ids]})
    assert r.status_code == 201, r.text
    brief = r.json()
    cleanup.append(brief["id"])
    return brief


async def patch(client, brief_id: str, **fields):
    return await client.patch(f"{BASE}/{brief_id}", json=fields)


COMPLETE = {
    "deliverables_count": 3,
    "deliverables_format": "short_video",
    "budget_ceiling_cents": 150000,
    "ask_price_cents": 100000,
    "negotiation_ask": "Three short videos at a launch-week rate",
    "flexibility": ["price"],
}


async def test_create_prefills_from_brand_and_product(brand_client, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"], seeded_ids["arjun"])

    assert brief["brand_name"] == "Lumen Audio"
    assert brief["product_name"] == "Lumen Pods"
    assert brief["product_summary"] == DEMO_PRODUCT_SUMMARY
    assert brief["contact_email"] == get_settings().demo_brand_email
    assert brief["status"] == "draft"
    assert brief["creator_ids"] == [str(seeded_ids["priya"]), str(seeded_ids["arjun"])]
    assert brief["approved_at"] is None
    assert brief["batch_id"] is None
    assert brief["missing"][0] == "deliverables_count"
    assert "brand_name" not in brief["missing"]
    assert brief["violations"] == []


async def test_create_dedupes_and_keeps_order(brand_client, brief_cleanup, seeded_ids):
    brief = await create(
        brand_client,
        brief_cleanup,
        seeded_ids["arjun"],
        seeded_ids["priya"],
        seeded_ids["arjun"],
    )
    assert brief["creator_ids"] == [str(seeded_ids["arjun"]), str(seeded_ids["priya"])]


async def test_create_rejects_unknown_creator(brand_client, seeded_ids):
    unknown = "00000000-0000-4000-8000-000000000001"
    r = await brand_client.post(BASE, json={"creator_ids": [str(seeded_ids["priya"]), unknown]})
    assert r.status_code == 422
    assert r.json()["detail"] == {"error": "unknown_creators", "creator_ids": [unknown]}


async def test_creator_cannot_create_brief(creator_client, seeded_ids):
    r = await creator_client.post(BASE, json={"creator_ids": [str(seeded_ids["arjun"])]})
    assert r.status_code == 403
    assert r.json()["detail"] == "wrong_role"


async def test_other_brand_gets_404(brand_client, new_brand_client, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"])
    url = f"{BASE}/{brief['id']}"

    for r in (
        await new_brand_client.get(url),
        await new_brand_client.patch(url, json={"deliverables_count": 2}),
        await new_brand_client.get(f"{url}/preview"),
    ):
        assert r.status_code == 404
        assert r.json()["detail"] == "brief_not_found"

    # Nothing was changed by the other brand's patch.
    assert (await brand_client.get(url)).json()["deliverables_count"] is None


async def test_unknown_brief_is_404(brand_client):
    r = await brand_client.get(f"{BASE}/00000000-0000-4000-8000-000000000002")
    assert r.status_code == 404
    assert r.json()["detail"] == "brief_not_found"


async def test_patch_rejects_invalid_field_with_message(brand_client, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"])

    r = await patch(brand_client, brief["id"], deliverables_count=3, go_live_by="2020-01-01")

    assert r.status_code == 422
    assert r.json()["detail"] == {
        "error": "invalid_field",
        "field": "go_live_by",
        "message": "The go-live date must be in the future.",
    }
    # Nothing else from the same body was saved.
    saved = (await brand_client.get(f"{BASE}/{brief['id']}")).json()
    assert saved["deliverables_count"] is None
    assert saved["go_live_by"] is None


async def test_patch_wrong_type_is_a_validation_error(brand_client, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"])
    r = await patch(brand_client, brief["id"], deliverables_count="abc")
    assert r.status_code == 422


async def test_patch_null_clears_a_field_and_omitted_fields_stay(
    brand_client, brief_cleanup, seeded_ids
):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"])
    r = await patch(brand_client, brief["id"], deliverables_count=2, flexibility=["timeline"])
    assert r.status_code == 200

    r = await patch(brand_client, brief["id"], brand_name=None, flexibility=None)

    assert r.status_code == 200
    body = r.json()
    assert body["brand_name"] is None
    assert body["flexibility"] == []
    assert body["deliverables_count"] == 2
    assert body["product_name"] == "Lumen Pods"
    assert "brand_name" in body["missing"]


async def test_patch_ask_over_ceiling_saved_as_violation(brand_client, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"])

    r = await patch(brand_client, brief["id"], budget_ceiling_cents=100000, ask_price_cents=200000)

    assert r.status_code == 200
    body = r.json()
    assert body["ask_price_cents"] == 200000
    assert body["budget_ceiling_cents"] == 100000
    assert [v["field"] for v in body["violations"]] == ["ask_price_cents"]
    assert body["status"] == "draft"
    assert (await brand_client.get(f"{BASE}/{brief['id']}")).json()["violations"] == body[
        "violations"
    ]


async def test_complete_brief_becomes_ready(brand_client, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"])

    r = await patch(brand_client, brief["id"], go_live_by=go_live(), **COMPLETE)

    assert r.status_code == 200
    body = r.json()
    assert body["missing"] == []
    assert body["violations"] == []
    assert body["status"] == "ready"

    # Breaking a rule again drops it back to a draft.
    r = await patch(brand_client, brief["id"], ask_price_cents=999999)
    assert r.json()["status"] == "draft"


async def test_patch_after_launch_409(brand_client, api_db, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"])
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.briefs set status = 'launched' where id = $1", UUID(brief["id"])
        )

    r = await patch(brand_client, brief["id"], deliverables_count=2)

    assert r.status_code == 409
    assert r.json()["detail"] == "brief_launched"
    got = await brand_client.get(f"{BASE}/{brief['id']}")
    assert got.json()["status"] == "launched"
    assert got.json()["deliverables_count"] is None


async def test_preview_deltas_and_default_channels(brand_client, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"], seeded_ids["arjun"])
    r = await patch(brand_client, brief["id"], go_live_by=go_live(), **COMPLETE)
    assert r.status_code == 200

    r = await brand_client.get(f"{BASE}/{brief['id']}/preview")

    assert r.status_code == 200, r.text
    creators = r.json()["creators"]
    assert [c["creator_id"] for c in creators] == [
        str(seeded_ids["priya"]),
        str(seeded_ids["arjun"]),
    ]
    priya, arjun = creators
    assert priya["handle"] == "priyareviews"
    assert priya["initials"] == "".join(w[0] for w in priya["name"].split()[:2]).upper()
    assert arjun["default_channel"] == "call"
    assert arjun["call_allowed"] is True
    assert priya["default_channel"] == "email"
    for c in creators:
        assert c["delta"]["headline"]
        assert c["delta"]["package_id"] == c["package"]["id"]
        assert c["delta"]["ask_videos"] == 3
        assert c["delta"]["ask_price_cents"] == 100000
        assert c["excluded_reason"] is None


async def test_preview_delta_null_until_ask_complete(brand_client, brief_cleanup, seeded_ids):
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"])

    async def deltas() -> list:
        r = await brand_client.get(f"{BASE}/{brief['id']}/preview")
        assert r.status_code == 200, r.text
        return [c["delta"] for c in r.json()["creators"]]

    assert await deltas() == [None]
    await patch(brand_client, brief["id"], deliverables_count=3, ask_price_cents=100000)
    assert await deltas() == [None]  # still no go-live date
    await patch(brand_client, brief["id"], go_live_by=go_live())
    [delta] = await deltas()
    assert delta is not None and delta["headline"]


async def test_preview_marks_opted_out_creator(brand_client, api_db, brief_cleanup):
    """A throwaway creator (committed, then deleted) who opted out of contact."""
    async with api_db.acquire() as conn:
        creator_id = await conn.fetchval(
            "insert into public.creators (handle, name, niches, email, phone, phone_opt_in,"
            " contact_opt_out) values ($1, 'Opt Out', '{consumer_tech}', 'optout@example.com',"
            " '+15555550123', true, true) returning id",
            f"optout_{uuid4().hex[:10]}",
        )
        await conn.execute(
            "insert into public.packages (creator_id, name, content_type, niche, volume_count,"
            " volume_basis, base_price_cents, preferred_channel, status)"
            " values ($1, 'Solo', 'short_video', 'consumer_tech', 1, 'per_contract', 50000,"
            " 'phone_ok', 'published')",
            creator_id,
        )
    try:
        brief = await create(brand_client, brief_cleanup, creator_id)
        r = await brand_client.get(f"{BASE}/{brief['id']}/preview")
        assert r.status_code == 200, r.text
        [creator] = r.json()["creators"]
        assert creator["excluded_reason"] == "Opted out of contact"
        assert creator["call_allowed"] is True
        assert "optout@example.com" not in r.text
        assert "+15555550123" not in r.text
    finally:
        async with api_db.acquire() as conn:
            await conn.execute(
                "delete from public.briefs where id = any($1::uuid[])", brief_cleanup
            )
            await conn.execute("delete from public.creators where id = $1", creator_id)


async def test_responses_never_expose_contact_or_floor(
    brand_client, api_db, brief_cleanup, seeded_ids
):
    async with api_db.acquire() as conn:
        creators = await conn.fetch(
            "select email, phone from public.creators where id = any($1)",
            [seeded_ids["priya"], seeded_ids["arjun"]],
        )
        floors = await conn.fetch(
            "select f.floor_price_cents from public.package_floors f"
            " join public.packages p on p.id = f.package_id where p.creator_id = any($1)",
            [seeded_ids["priya"], seeded_ids["arjun"]],
        )
    secrets = [v for row in creators for v in (row["email"], row["phone"]) if v]
    assert secrets, "the seeded creators have contact details"
    # Numbers the test itself sends back to the API may legitimately equal a floor.
    sent = {1, 3, 100000, 150000}
    floor_values = {row["floor_price_cents"] for row in floors} - sent
    assert floor_values

    responses = []
    brief = await create(brand_client, brief_cleanup, seeded_ids["priya"], seeded_ids["arjun"])
    responses.append(
        await brand_client.post(BASE, json={"creator_ids": [str(seeded_ids["priya"])]})
    )
    brief_cleanup.append(responses[0].json()["id"])
    responses.append(await brand_client.get(f"{BASE}/{brief['id']}"))
    responses.append(await patch(brand_client, brief["id"], go_live_by=go_live(), **COMPLETE))
    responses.append(await brand_client.get(f"{BASE}/{brief['id']}/preview"))

    for r in responses:
        assert r.status_code in (200, 201), r.text
        for secret in secrets:
            assert secret not in r.text
        assert "floor" not in r.text.lower()
        for value in floor_values:
            assert not re.search(rf"(?<!\d){value}(?!\d)", r.text), value

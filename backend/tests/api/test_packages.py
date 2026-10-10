"""The creator packages API: /me/packages.

Tests that write (create, patch, publish, floor) run as `new_creator_client`, a throwaway
creator that is deleted afterwards; the seeded creators' rows are never modified. Reading
and dictating (which saves nothing) may use the seeded Priya (`creator_client`).
Gemini is a fake throughout.
"""

from uuid import UUID

import pytest

from app.adapters.gemini import GeminiInvalidOutput, GeminiUnavailable
from app.api.deps import get_gemini
from app.core.package_text import creator_embedding_document, text_hash
from app.schemas.packages import ExtractedDraft, PackageDraft, PackageTerms

pytestmark = pytest.mark.db

BASE = "/api/v1/me/packages"
SEARCH = "/api/v1/discovery/search"
# What `new_creator_client` onboards with.
CREATOR_NAME = "Test Creator"
CREATOR_NICHES = ["consumer_tech"]
INDEX_PENDING = ["search index update pending"]

COMPLETE = {
    "name": "Launch Duo",
    "content_type": "short_video",
    "niche": "consumer_tech",
    "volume_count": 2,
    "volume_basis": "per_contract",
    "base_price_cents": 100000,
    "preferred_channel": "phone_ok",
}


async def create(client, **overrides) -> dict:
    r = await client.post(BASE, json={**COMPLETE, **overrides})
    assert r.status_code == 201, r.text
    return r.json()


async def publish(client, package_id: str) -> dict:
    r = await client.post(f"{BASE}/{package_id}/publish")
    assert r.status_code == 200, r.text
    return r.json()


async def my_creator(client) -> dict:
    return (await client.get("/api/v1/me")).json()["creator"]


async def search_index(api_db, client) -> tuple[str | None, bool]:
    """(hash of the document the creator's embedding was made from, has an embedding)."""
    creator = await my_creator(client)
    async with api_db.acquire() as conn:
        row = await conn.fetchrow(
            "select embedding_text_hash, embedding is not null as has_embedding"
            " from public.creators where id = $1",
            UUID(creator["id"]),
        )
    return row["embedding_text_hash"], row["has_embedding"]


def index_hash(*packages: dict) -> str:
    """The hash of the embedding document for the throwaway creator with these packages."""
    terms = [PackageTerms(**{**COMPLETE, **package}) for package in packages]
    return text_hash(*creator_embedding_document(CREATOR_NAME, "", CREATOR_NICHES, terms))


async def package_state(api_db, package_id) -> tuple:
    async with api_db.acquire() as conn:
        row = await conn.fetchrow(
            "select p.name, p.status, p.base_price_cents, p.updated_at, f.floor_price_cents"
            " from public.packages p left join public.package_floors f on f.package_id = p.id"
            " where p.id = $1",
            UUID(str(package_id)),
        )
    return tuple(row.values())


# Dictating a package ----------------------------------------------------------------


async def test_draft_from_speech_merges_and_reports_missing(creator_client, fake_gemini):
    fake_gemini.queue_structured(
        ExtractedDraft(
            heard="two videos per contract for a thousand",
            draft=PackageDraft(
                volume_count=2, volume_basis="per_contract", base_price_cents=100000
            ),
        )
    )
    r = await creator_client.post(
        f"{BASE}/draft-from-speech",
        json={
            "transcript": "um two videos per contract for a thousand",
            "current": {"name": "Duo"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["draft"]["name"] == "Duo" and body["draft"]["volume_count"] == 2
    assert body["draft"]["base_price_cents"] == 100000
    assert body["missing"] == ["content_type", "niche", "preferred_channel"]
    assert body["violations"] == []
    assert body["heard"] == "two videos per contract for a thousand"


async def test_draft_from_speech_saves_nothing(creator_client, fake_gemini):
    before = (await creator_client.get(BASE)).json()
    fake_gemini.queue_structured(ExtractedDraft(heard="x", draft=PackageDraft(name="Ghost")))

    await creator_client.post(f"{BASE}/draft-from-speech", json={"transcript": "call it Ghost"})

    assert (await creator_client.get(BASE)).json() == before


async def test_unusable_model_reply_leaves_the_draft_as_it_was(creator_client, fake_gemini):
    fake_gemini.queue_structured({"heard": "x", "draft": {"volume_count": "lots"}})

    r = await creator_client.post(
        f"{BASE}/draft-from-speech",
        json={"transcript": "mumble mumble", "current": {"name": "Duo"}},
    )

    assert r.status_code == 200
    assert r.json()["draft"]["name"] == "Duo" and r.json()["draft"]["volume_count"] is None
    assert r.json()["heard"] == "mumble mumble"
    assert r.json()["missing"][0] == "content_type"


async def test_model_down_is_503_voice_unavailable(creator_client, app):
    class Down:
        async def generate_structured(self, **_):
            raise GeminiUnavailable("down")

    app.dependency_overrides[get_gemini] = lambda: Down()

    r = await creator_client.post(f"{BASE}/draft-from-speech", json={"transcript": "x"})

    assert r.status_code == 503
    assert r.json() == {"detail": "voice_unavailable"}


@pytest.mark.parametrize("body", [{}, {"transcript": ""}, {"transcript": "  "}])
async def test_draft_from_speech_needs_a_transcript(creator_client, fake_gemini, body):
    r = await creator_client.post(f"{BASE}/draft-from-speech", json=body)
    assert r.status_code == 422
    assert fake_gemini.calls == []


# Saving and listing ----------------------------------------------------------------------


async def test_create_saves_an_unpublished_package(new_creator_client):
    body = {
        **COMPLETE,
        "included": ["One revision round"],
        "freebies": ["Pinned comment"],
        "addons": [{"name": "Extra video", "price_cents": 40000, "unit": "video"}],
        "extras": [{"name": "Raw footage", "price_cents": 30000}],
        "slots_per_month": 3,
    }
    r = await new_creator_client.post(BASE, json=body)

    assert r.status_code == 201
    pkg = r.json()
    assert pkg["status"] == "draft" and pkg["floor_price_cents"] is None
    assert UUID(pkg["id"])
    assert pkg["one_liner"] == "2 videos/contract · $1,000 · +1 video $400"
    assert pkg["per_video_cents"] == 50000
    assert pkg["currency"] == "USD" and pkg["lead_time_days"] is None
    assert pkg["included"] == ["One revision round"] and pkg["freebies"] == ["Pinned comment"]
    assert pkg["addons"] == body["addons"] and pkg["extras"] == body["extras"]
    assert pkg["slots_per_month"] == 3
    assert (await new_creator_client.get(BASE)).json() == [pkg]


async def test_create_without_required_fields_lists_what_is_missing(new_creator_client):
    r = await new_creator_client.post(BASE, json={"name": "Duo", "volume_count": 2})

    assert r.status_code == 422
    assert r.json()["detail"] == {
        "error": "draft_incomplete",
        "missing": [
            "content_type",
            "niche",
            "volume_basis",
            "base_price_cents",
            "preferred_channel",
        ],
    }
    assert (await new_creator_client.get(BASE)).json() == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volume_count", 0),
        ("base_price_cents", 0),
        ("slots_per_month", -1),
        ("lead_time_days", -1),
        ("base_price_cents", 2**31),
    ],
)
async def test_create_refuses_numbers_the_database_cannot_store(new_creator_client, field, value):
    r = await new_creator_client.post(BASE, json={**COMPLETE, field: value})

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "rules_violated"
    assert [v["field"] for v in detail["violations"]] == [field]
    assert (await new_creator_client.get(BASE)).json() == []


async def test_list_has_drafts_and_published_cheapest_first_with_floors(new_creator_client):
    pricey = await create(new_creator_client, name="Pricey", base_price_cents=200000)
    cheap = await create(new_creator_client, name="Cheap", base_price_cents=50000)
    await publish(new_creator_client, cheap["id"])
    await new_creator_client.put(f"{BASE}/{pricey['id']}/floor", json={"floor_price_cents": 150000})

    r = await new_creator_client.get(BASE)

    assert [(p["name"], p["status"], p["floor_price_cents"]) for p in r.json()] == [
        ("Cheap", "published", None),
        ("Pricey", "draft", 150000),
    ]


async def test_list_returns_only_my_packages(creator_client, other_package_id):
    r = await creator_client.get(BASE)

    assert r.status_code == 200
    packages = r.json()
    assert packages and str(other_package_id) not in {p["id"] for p in packages}
    assert all(p["floor_price_cents"] is not None for p in packages)  # the seed sets every floor


# Patching ------------------------------------------------------------------------------


async def test_patch_changes_only_the_fields_sent(new_creator_client, api_db):
    pkg = await create(new_creator_client, lead_time_days=14)
    before = await package_state(api_db, pkg["id"])

    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"base_price_cents": 90000})

    assert r.status_code == 200
    patched = r.json()
    assert patched["base_price_cents"] == 90000 and patched["per_video_cents"] == 45000
    assert patched["name"] == "Launch Duo" and patched["lead_time_days"] == 14
    assert patched["status"] == "draft" and patched["warnings"] == []
    after = await package_state(api_db, pkg["id"])
    assert after[3] > before[3]  # updated_at moved: the table has no trigger for it


async def test_patch_replaces_lists_and_clears_optional_fields(new_creator_client):
    pkg = await create(
        new_creator_client,
        included=["Script approval", "One revision round"],
        addons=[{"name": "Rush", "price_cents": 2000, "unit": "item"}],
        lead_time_days=14,
    )

    r = await new_creator_client.patch(
        f"{BASE}/{pkg['id']}",
        json={"included": ["Script approval"], "addons": [], "lead_time_days": None},
    )

    assert r.status_code == 200
    assert r.json()["included"] == ["Script approval"]
    assert r.json()["addons"] == [] and r.json()["lead_time_days"] is None


@pytest.mark.parametrize("patch", [{"name": None}, {"name": "  "}])
async def test_patch_cannot_blank_a_required_field(new_creator_client, patch):
    pkg = await create(new_creator_client)

    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json=patch)

    assert r.status_code == 422
    assert r.json()["detail"] == {"error": "draft_incomplete", "missing": ["name"]}
    assert (await new_creator_client.get(BASE)).json() == [pkg]


async def test_patch_refuses_numbers_the_database_cannot_store(new_creator_client):
    pkg = await create(new_creator_client)

    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"volume_count": 0})

    assert r.status_code == 422
    assert r.json()["detail"]["violations"][0]["field"] == "volume_count"
    assert (await new_creator_client.get(BASE)).json() == [pkg]


async def test_patch_cannot_drop_the_base_price_below_the_floor(new_creator_client):
    pkg = await create(new_creator_client)
    await new_creator_client.put(f"{BASE}/{pkg['id']}/floor", json={"floor_price_cents": 80000})

    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"base_price_cents": 70000})

    assert r.status_code == 422
    [violation] = r.json()["detail"]["violations"]
    assert violation["field"] == "base_price_cents" and "$800" in violation["message"]
    assert (await new_creator_client.get(BASE)).json()[0]["base_price_cents"] == 100000
    ok = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"base_price_cents": 80000})
    assert ok.status_code == 200


async def test_a_draft_may_hold_a_niche_the_creator_does_not_cover_until_it_is_published(
    new_creator_client,
):
    pkg = await create(new_creator_client)

    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"niche": "beauty"})

    assert r.status_code == 200 and r.json()["niche"] == "beauty"


async def test_a_published_package_must_keep_passing_the_publishing_rules(new_creator_client):
    pkg = await create(new_creator_client)
    await publish(new_creator_client, pkg["id"])

    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"niche": "beauty"})

    assert r.status_code == 422
    assert [v["field"] for v in r.json()["detail"]["violations"]] == ["niche"]
    assert (await new_creator_client.get(BASE)).json()[0]["niche"] == "consumer_tech"


async def test_editing_a_draft_leaves_the_search_index_alone(new_creator_client, fake_gemini):
    pkg = await create(new_creator_client)

    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"base_price_cents": 90000})

    assert r.status_code == 200 and fake_gemini.embed_calls == 0


async def test_editing_a_published_package_reembeds_only_when_the_embedded_text_changes(
    new_creator_client, fake_gemini, api_db
):
    pkg = await create(new_creator_client)
    await publish(new_creator_client, pkg["id"])
    assert fake_gemini.embed_calls == 1

    # Lead time is not part of the embedded text.
    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"lead_time_days": 7})
    assert r.status_code == 200 and r.json()["warnings"] == []
    assert fake_gemini.embed_calls == 1

    # The price is part of the package's one-liner.
    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"base_price_cents": 90000})
    assert r.status_code == 200 and r.json()["warnings"] == []
    assert fake_gemini.embed_calls == 2
    assert await search_index(api_db, new_creator_client) == (
        index_hash({"base_price_cents": 90000}),
        True,
    )


async def test_editing_a_published_package_warns_when_the_index_update_fails(
    new_creator_client, fake_gemini
):
    pkg = await create(new_creator_client)
    await publish(new_creator_client, pkg["id"])
    fake_gemini.embed_failure = GeminiUnavailable("down")

    r = await new_creator_client.patch(f"{BASE}/{pkg['id']}", json={"base_price_cents": 90000})

    assert r.status_code == 200
    assert r.json()["base_price_cents"] == 90000 and r.json()["warnings"] == INDEX_PENDING


# Publishing ---------------------------------------------------------------------------


async def test_publish_blocked_with_violations(new_creator_client, fake_gemini):
    pkg = await create(new_creator_client, niche="beauty")  # the creator covers consumer tech

    r = await new_creator_client.post(f"{BASE}/{pkg['id']}/publish")

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "rules_violated"
    [violation] = detail["violations"]
    assert violation["field"] == "niche" and "consumer tech" in violation["message"]
    assert (await new_creator_client.get(BASE)).json()[0]["status"] == "draft"
    assert fake_gemini.embed_calls == 0


async def test_publish_reembeds_when_text_changes(new_creator_client, fake_gemini, api_db):
    pkg = await create(new_creator_client)
    assert await search_index(api_db, new_creator_client) == (None, False)

    published = await publish(new_creator_client, pkg["id"])

    assert published["status"] == "published" and published["warnings"] == []
    assert fake_gemini.embed_calls == 1
    assert await search_index(api_db, new_creator_client) == (index_hash({}), True)


async def test_publish_skips_embed_when_unchanged(new_creator_client, fake_gemini):
    pkg = await create(new_creator_client)
    await publish(new_creator_client, pkg["id"])
    assert fake_gemini.embed_calls == 1

    again = await publish(new_creator_client, pkg["id"])

    assert again["status"] == "published" and again["warnings"] == []
    assert fake_gemini.embed_calls == 1


async def test_publishing_a_second_package_updates_the_embedding(
    new_creator_client, fake_gemini, api_db
):
    first = await create(new_creator_client)
    second = await create(new_creator_client, name="Deep Dive", base_price_cents=280000)
    await publish(new_creator_client, first["id"])

    await publish(new_creator_client, second["id"])

    assert fake_gemini.embed_calls == 2
    assert await search_index(api_db, new_creator_client) == (
        index_hash({}, {"name": "Deep Dive", "base_price_cents": 280000}),
        True,
    )


@pytest.mark.parametrize("failure", [GeminiUnavailable("down"), GeminiInvalidOutput("bad")])
async def test_publish_survives_an_embedding_failure_and_retries_next_time(
    new_creator_client, fake_gemini, api_db, failure
):
    pkg = await create(new_creator_client)
    fake_gemini.embed_failure = failure

    r = await new_creator_client.post(f"{BASE}/{pkg['id']}/publish")

    assert r.status_code == 200
    assert r.json()["status"] == "published" and r.json()["warnings"] == INDEX_PENDING
    assert (await new_creator_client.get(BASE)).json()[0]["status"] == "published"
    assert await search_index(api_db, new_creator_client) == (None, False)

    fake_gemini.embed_failure = None
    retried = await publish(new_creator_client, pkg["id"])

    assert retried["warnings"] == [] and fake_gemini.embed_calls == 2
    assert await search_index(api_db, new_creator_client) == (index_hash({}), True)


async def test_published_package_visible_in_discovery(new_creator_client, brand_client):
    handle = (await my_creator(new_creator_client))["handle"]
    pkg = await create(new_creator_client, name="Visible Duo", base_price_cents=12345)
    cheap = {"filters": {"max_price_cents": 12345}, "limit": 48}

    async def creators_found() -> dict[str, dict]:
        r = await brand_client.post(SEARCH, json=cheap)
        assert r.status_code == 200
        return {card["handle"]: card for card in r.json()["results"]}

    assert handle not in await creators_found()  # a draft is not in the marketplace

    await publish(new_creator_client, pkg["id"])
    await new_creator_client.put(f"{BASE}/{pkg['id']}/floor", json={"floor_price_cents": 10000})

    card = (await creators_found())[handle]
    assert [p["id"] for p in card["packages"]] == [pkg["id"]]
    assert card["packages"][0]["one_liner"] == "2 videos/contract · $123.45"
    assert "floor" not in str(card)


# The private floor -------------------------------------------------------------------


async def test_floor_is_saved_and_can_be_changed(new_creator_client):
    pkg = await create(new_creator_client)

    r = await new_creator_client.put(f"{BASE}/{pkg['id']}/floor", json={"floor_price_cents": 80000})
    assert r.status_code == 200 and r.json()["floor_price_cents"] == 80000
    assert r.json()["id"] == pkg["id"] and r.json()["status"] == "draft"

    r = await new_creator_client.put(
        f"{BASE}/{pkg['id']}/floor", json={"floor_price_cents": 100000}
    )
    assert r.status_code == 200 and r.json()["floor_price_cents"] == 100000  # equal to base is fine
    assert (await new_creator_client.get(BASE)).json()[0]["floor_price_cents"] == 100000


async def test_floor_above_base_422(new_creator_client):
    pkg = await create(new_creator_client)
    await new_creator_client.put(f"{BASE}/{pkg['id']}/floor", json={"floor_price_cents": 80000})

    r = await new_creator_client.put(
        f"{BASE}/{pkg['id']}/floor", json={"floor_price_cents": 100001}
    )

    assert r.status_code == 422
    [violation] = r.json()["detail"]["violations"]
    assert violation["field"] == "floor_price_cents" and "$1,000" in violation["message"]
    assert (await new_creator_client.get(BASE)).json()[0]["floor_price_cents"] == 80000


@pytest.mark.parametrize("floor", [0, -5, "cheap", 1.5])
async def test_floor_must_be_a_positive_whole_number_of_cents(new_creator_client, floor):
    pkg = await create(new_creator_client)

    r = await new_creator_client.put(f"{BASE}/{pkg['id']}/floor", json={"floor_price_cents": floor})

    assert r.status_code == 422
    assert (await new_creator_client.get(BASE)).json()[0]["floor_price_cents"] is None


# Who may use it -----------------------------------------------------------------------


async def test_other_creators_package_404(new_creator_client, other_package_id, api_db):
    before = await package_state(api_db, other_package_id)
    name, _, _, _, floor = before
    # Requests that would change nothing even if the ownership check failed.
    attempts = [
        new_creator_client.patch(f"{BASE}/{other_package_id}", json={"name": name}),
        new_creator_client.post(f"{BASE}/{other_package_id}/publish"),
        new_creator_client.put(
            f"{BASE}/{other_package_id}/floor", json={"floor_price_cents": floor}
        ),
    ]

    for attempt in attempts:
        r = await attempt
        assert r.status_code == 404
        assert r.json() == {"detail": "package_not_found"}
    assert await package_state(api_db, other_package_id) == before


async def test_unknown_package_404(new_creator_client):
    nothing = "00000000-0000-4000-8000-000000000000"

    r = await new_creator_client.post(f"{BASE}/{nothing}/publish")

    assert r.status_code == 404 and r.json() == {"detail": "package_not_found"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "", None),
        ("POST", "/draft-from-speech", {"transcript": "x"}),
        ("POST", "", COMPLETE),
        ("PATCH", "/00000000-0000-4000-8000-000000000000", {"name": "x"}),
        ("POST", "/00000000-0000-4000-8000-000000000000/publish", None),
        ("PUT", "/00000000-0000-4000-8000-000000000000/floor", {"floor_price_cents": 1}),
    ],
)
async def test_brand_403(brand_client, method, path, body):
    r = await brand_client.request(method, BASE + path, json=body)

    assert r.status_code == 403
    assert r.json() == {"detail": "wrong_role"}


async def test_signing_in_is_required(client, fake_jwks):
    r = await client.get(BASE)

    assert r.status_code == 401


async def test_a_creator_profile_without_a_creator_row_must_finish_onboarding(
    new_creator_client, api_db
):
    me = (await new_creator_client.get("/api/v1/me")).json()
    async with api_db.acquire() as conn:
        await conn.execute("delete from public.creators where profile_id = $1", UUID(me["user_id"]))

    r = await new_creator_client.get(BASE)

    assert r.status_code == 409 and r.json() == {"detail": "onboarding_required"}

"""POST /discovery/search and GET /creators/{id} against the seeded marketplace.

Read-only: the seed holds 40 creators, 77 published packages (and 3 drafts), the demo
brand, and Arjun (`arjuntech`) and Priya (`priyareviews`) as demo creators.
"""

import pytest

from app.adapters.gemini import GeminiInvalidOutput, GeminiUnavailable, format_query
from app.api.deps import get_gemini
from tests.fakes import fake_embedding

pytestmark = pytest.mark.db

SEARCH = "/api/v1/discovery/search"
SEEDED_CREATORS = 40
SEEDED_PUBLISHED_PACKAGES = 77
DEMO_QUERY = "tech creators doing short-form reviews under two thousand dollars"

CARD_KEYS = {
    "id",
    "handle",
    "name",
    "initials",
    "niches",
    "region",
    "followers",
    "engagement_rate",
    "packages",
}
PACKAGE_KEYS = {
    "id",
    "name",
    "content_type",
    "niche",
    "volume_count",
    "volume_basis",
    "base_price_cents",
    "per_video_cents",
    "one_liner",
    "lead_time_days",
    "preferred_channel",
    "addons",
}
PRIVATE_KEYS = {
    "floor_price_cents",
    "email",
    "phone",
    "phone_opt_in",
    "contact_opt_out",
    "embedding",
    "embedding_text_hash",
    "profile_id",
}


def all_keys(value) -> set[str]:
    """Every object key anywhere in a decoded JSON value."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in all_keys(item)}
    return set()


async def everyone(brand_client) -> list[dict]:
    """All seeded creators' cards, as an unfiltered search returns them."""
    r = await brand_client.post(SEARCH, json={"limit": 48})
    assert r.status_code == 200
    return r.json()["results"]


async def arjun(brand_client) -> dict:
    return next(card for card in await everyone(brand_client) if card["handle"] == "arjuntech")


# Search ---------------------------------------------------------------------


async def test_filters_only_does_not_embed(brand_client, fake_gemini):
    r = await brand_client.post(
        SEARCH,
        json={
            "filters": {
                "niches": ["consumer_tech"],
                "content_types": ["short_video"],
                "max_price_cents": 200000,
            }
        },
    )
    assert r.status_code == 200 and len(r.json()["results"]) >= 12
    assert fake_gemini.embed_calls == 0
    assert all(
        any(
            p["base_price_cents"] <= 200000 and p["content_type"] == "short_video"
            for p in c["packages"]
        )
        for c in r.json()["results"]
    )
    assert all("consumer_tech" in c["niches"] for c in r.json()["results"])


async def test_without_a_query_the_most_followed_come_first(brand_client):
    cards = await everyone(brand_client)
    followers = [card["followers"] for card in cards]
    assert len(cards) == SEEDED_CREATORS
    assert followers == sorted(followers, reverse=True)


async def test_query_embeds_once_and_ranks_by_distance(brand_client, fake_gemini, api_db):
    r = await brand_client.post(SEARCH, json={"query": DEMO_QUERY, "limit": 10})

    assert r.status_code == 200
    assert fake_gemini.embed_calls == 1
    body = r.json()
    assert body["query"] == DEMO_QUERY
    async with api_db.acquire() as conn:
        expected = await conn.fetch(
            "select creator_id from public.match_creators("
            "query_embedding => $1, match_limit => 10)",
            fake_embedding(format_query(DEMO_QUERY)),
        )
    assert [card["id"] for card in body["results"]] == [str(row["creator_id"]) for row in expected]


async def test_query_and_filters_combine(brand_client, fake_gemini):
    r = await brand_client.post(
        SEARCH, json={"query": DEMO_QUERY, "filters": {"region": "IN", "min_followers": 100000}}
    )

    assert r.status_code == 200
    results = r.json()["results"]
    assert any(card["handle"] == "arjuntech" for card in results)
    assert all(card["region"] == "IN" and card["followers"] >= 100000 for card in results)
    assert fake_gemini.embed_calls == 1


async def test_blank_query_and_region_are_ignored(brand_client, fake_gemini):
    r = await brand_client.post(SEARCH, json={"query": "   ", "filters": {"region": " "}})

    assert r.status_code == 200
    body = r.json()
    assert body["query"] is None and body["filters"]["region"] is None
    assert len(body["results"]) == 24
    assert fake_gemini.embed_calls == 0


async def test_response_echoes_the_applied_search(brand_client):
    filters = {
        "niches": ["gaming"],
        "content_types": ["live"],
        "max_price_cents": 500000,
        "min_followers": 1000,
        "region": "US",
    }
    r = await brand_client.post(SEARCH, json={"filters": filters})

    assert r.status_code == 200
    assert r.json()["query"] is None
    assert r.json()["filters"] == filters


async def test_limit_caps_the_results(brand_client):
    r = await brand_client.post(SEARCH, json={"limit": 5})
    assert r.status_code == 200 and len(r.json()["results"]) == 5


@pytest.mark.parametrize(
    "body",
    [
        {"limit": 0},
        {"limit": 49},
        {"filters": {"max_price_cents": 0}},
        {"filters": {"min_followers": -1}},
        {"filters": {"niches": ["knitting"]}},
        {"filters": {"content_types": ["podcast"]}},
        {"query": "x" * 501},
    ],
)
async def test_invalid_requests_are_rejected(brand_client, fake_gemini, body):
    r = await brand_client.post(SEARCH, json=body)
    assert r.status_code == 422
    assert fake_gemini.embed_calls == 0


@pytest.mark.parametrize("failure", [GeminiUnavailable("down"), GeminiInvalidOutput("bad")])
async def test_embedding_failure_is_search_unavailable(brand_client, app, failure):
    class FailingGemini:
        async def embed_query(self, query: str) -> list[float]:
            raise failure

    app.dependency_overrides[get_gemini] = lambda: FailingGemini()

    r = await brand_client.post(SEARCH, json={"query": DEMO_QUERY})
    assert r.status_code == 503
    assert r.json() == {"detail": "search_unavailable"}

    # Filter-only searches never need Gemini, so they still work.
    r = await brand_client.post(SEARCH, json={"filters": {"niches": ["beauty"]}})
    assert r.status_code == 200


# Cards ----------------------------------------------------------------------


async def test_response_never_contains_private_fields(brand_client):
    r = await brand_client.post(SEARCH, json={"limit": 48})

    results = r.json()["results"]
    assert len(results) == SEEDED_CREATORS
    # Keys, not substrings: `preferred_channel` values such as "email_first" and
    # "phone_ok" are public and contain those words.
    assert not all_keys(r.json()) & PRIVATE_KEYS
    for card in results:
        assert set(card) == CARD_KEYS
        for package in card["packages"]:
            assert set(package) == PACKAGE_KEYS


async def test_cards_list_only_published_packages_cheapest_first(brand_client):
    cards = await everyone(brand_client)

    assert sum(len(card["packages"]) for card in cards) == SEEDED_PUBLISHED_PACKAGES
    for card in cards:
        order = [(p["base_price_cents"], p["name"]) for p in card["packages"]]
        assert card["packages"] and order == sorted(order)


async def test_package_strip_text(brand_client, other_package_id):
    card = await arjun(brand_client)

    assert card["name"] == "Arjun Mehta"
    assert card["initials"] == "AM"
    assert card["niches"] == ["consumer_tech"]
    assert card["region"] == "IN"
    assert card["followers"] == 142000
    assert card["engagement_rate"] == 5.8  # percentage points, as stored
    launch_duo, deep_dive = card["packages"]
    assert launch_duo["id"] == str(other_package_id)
    assert launch_duo["one_liner"] == "2 videos/contract · $1,000 · +1 video $400"
    assert launch_duo["per_video_cents"] == 50000
    assert launch_duo["addons"] == [{"name": "Extra video", "price_cents": 40000, "unit": "video"}]
    assert launch_duo["lead_time_days"] == 14
    assert deep_dive["name"] == "Deep Dive Review"
    assert deep_dive["content_type"] == "long_video"
    assert deep_dive["addons"] == []


# Roles ----------------------------------------------------------------------


async def test_creator_role_gets_403(creator_client):
    r = await creator_client.post(SEARCH, json={})
    assert r.status_code == 403
    assert r.json() == {"detail": "wrong_role"}


async def test_search_requires_a_signed_in_user(client, fake_jwks, api_db):
    r = await client.post(SEARCH, json={})
    assert r.status_code == 401


# GET /creators/{id} ---------------------------------------------------------


async def test_get_creator_returns_the_same_card_as_search(brand_client, fake_gemini):
    card = await arjun(brand_client)

    r = await brand_client.get(f"/api/v1/creators/{card['id']}")

    assert r.status_code == 200
    assert r.json() == card
    assert not all_keys(r.json()) & PRIVATE_KEYS
    assert fake_gemini.embed_calls == 0


async def test_get_unknown_creator_is_404(brand_client):
    r = await brand_client.get("/api/v1/creators/00000000-0000-4000-8000-000000000000")
    assert r.status_code == 404
    assert r.json() == {"detail": "creator_not_found"}


async def test_get_creator_with_a_malformed_id_is_422(brand_client):
    r = await brand_client.get("/api/v1/creators/not-a-uuid")
    assert r.status_code == 422


async def test_creator_role_cannot_get_creators(creator_client, brand_client):
    card = await arjun(brand_client)
    r = await creator_client.get(f"/api/v1/creators/{card['id']}")
    assert r.status_code == 403

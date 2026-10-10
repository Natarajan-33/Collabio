"""`match_creators`: hard filters on published packages, then distance or follower order.

Every call filters on `factory.region` so creators already in the database never leak in.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.db

EMBEDDING_DIM = 768


def unit_vector(axis: int) -> list[float]:
    """A deterministic unit vector along `axis`; distinct axes have cosine distance 1."""
    vector = [0.0] * EMBEDDING_DIM
    vector[axis] = 1.0
    return vector


async def match(conn: asyncpg.Connection, factory, **params: object) -> list:
    """Call match_creators with named arguments, scoped to this test's region."""
    params = {"region": factory.region, **params}
    args = ", ".join(f"{name} => ${i}" for i, name in enumerate(params, start=1))
    return await conn.fetch(
        f"select creator_id, distance from public.match_creators({args})", *params.values()
    )


def creator_ids(rows: list) -> list:
    return [row["creator_id"] for row in rows]


async def test_filters_by_max_price_and_content_type(db_conn, factory):
    a = await factory.creator()
    b = await factory.creator()
    await factory.package(a.id, content_type="short_video", base_price_cents=100_000)
    await factory.package(b.id, content_type="long_video", base_price_cents=300_000)

    rows = await match(db_conn, factory, max_price_cents=200_000, content_types=["short_video"])

    assert creator_ids(rows) == [a.id]


async def test_price_and_content_type_must_hold_on_the_same_package(db_conn, factory):
    creator = await factory.creator()
    await factory.package(creator.id, content_type="short_video", base_price_cents=300_000)
    await factory.package(creator.id, content_type="long_video", base_price_cents=100_000)

    rows = await match(db_conn, factory, max_price_cents=200_000, content_types=["short_video"])

    assert rows == []


async def test_empty_filter_lists_are_not_applied(db_conn, factory):
    creator = await factory.creator(niches=["beauty"])
    await factory.package(creator.id, content_type="story")

    rows = await match(db_conn, factory, content_types=[], niches=[])

    assert creator_ids(rows) == [creator.id]


async def test_filters_by_niches_and_min_followers(db_conn, factory):
    tech_big = await factory.creator(niches=["consumer_tech", "gaming"], followers=50_000)
    tech_small = await factory.creator(niches=["consumer_tech"], followers=2_000)
    beauty_big = await factory.creator(niches=["beauty"], followers=80_000)
    for creator in (tech_big, tech_small, beauty_big):
        await factory.package(creator.id)

    rows = await match(db_conn, factory, niches=["gaming", "consumer_tech"], min_followers=10_000)

    assert creator_ids(rows) == [tech_big.id]


async def test_orders_by_distance_when_embedding_given(db_conn, factory):
    a = await factory.creator(embedding=unit_vector(0), followers=1_000)
    b = await factory.creator(embedding=unit_vector(1), followers=90_000)
    await factory.package(a.id)
    await factory.package(b.id)

    rows = await match(db_conn, factory, query_embedding=unit_vector(0))

    assert creator_ids(rows) == [a.id, b.id]
    assert rows[0]["distance"] < 1e-6
    assert rows[1]["distance"] == pytest.approx(1.0)


async def test_ignores_draft_packages(db_conn, factory):
    published = await factory.creator()
    draft_only = await factory.creator()
    await factory.package(published.id, status="published")
    await factory.package(draft_only.id, status="draft")

    rows = await match(db_conn, factory)

    assert creator_ids(rows) == [published.id]


async def test_null_embedding_orders_by_followers_desc(db_conn, factory):
    small = await factory.creator(followers=1_000)
    big = await factory.creator(followers=5_000)
    medium = await factory.creator(followers=3_000)
    for creator in (small, big, medium):
        await factory.package(creator.id)

    rows = await match(db_conn, factory)

    assert creator_ids(rows) == [big.id, medium.id, small.id]
    assert all(row["distance"] is None for row in rows)


async def test_respects_match_limit(db_conn, factory):
    for followers in (1_000, 2_000, 3_000):
        creator = await factory.creator(followers=followers)
        await factory.package(creator.id)

    rows = await match(db_conn, factory, match_limit=2)

    assert len(rows) == 2

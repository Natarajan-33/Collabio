"""Creator card loading: published packages only, cheapest first, in the order asked for.

Runs on rows created inside the rolled-back test transaction, so the seed is untouched.
"""

import uuid
from contextlib import asynccontextmanager

import pytest

from app.modules.discovery import repo, service

pytestmark = pytest.mark.db


class ConnectionDatabase:
    """Serves the test transaction's connection where the service wants a `Database`."""

    def __init__(self, conn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


async def test_cards_come_back_in_the_order_asked_for_and_skip_unknown_ids(db_conn, factory):
    first = await factory.creator()
    second = await factory.creator()
    third = await factory.creator()

    ids = [third.id, uuid.uuid4(), first.id, second.id]
    cards = await repo.fetch_cards(db_conn, ids)

    assert [card["id"] for card in cards] == [third.id, first.id, second.id]


async def test_cards_hold_published_packages_only_cheapest_first(db_conn, factory):
    creator = await factory.creator()
    dear = await factory.package(creator.id, base_price_cents=300_000)
    await factory.package(creator.id, base_price_cents=50_000, status="draft")
    cheap = await factory.package(creator.id, base_price_cents=120_000)

    [card] = await repo.fetch_cards(db_conn, [creator.id])

    assert [package["id"] for package in card["packages"]] == [str(cheap), str(dear)]


async def test_a_creator_with_no_published_package_has_no_packages_and_no_public_card(
    db_conn, factory
):
    creator = await factory.creator()
    await factory.package(creator.id, status="draft")

    [card] = await repo.fetch_cards(db_conn, [creator.id])

    assert card["packages"] == []
    assert await service.get_creator(ConnectionDatabase(db_conn), creator.id) is None


async def test_card_never_carries_floors_or_contact_details(db_conn, factory):
    creator = await factory.creator()
    await factory.package(creator.id, floor_price_cents=60_000)

    card = await service.get_creator(ConnectionDatabase(db_conn), creator.id)

    assert card is not None
    assert "60000" not in card.model_dump_json()
    assert "test.collabio.invalid" not in card.model_dump_json()

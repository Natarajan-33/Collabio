"""The asyncpg `Database` adapter: pgvector codec, search_path, transactions."""

import pytest
from pgvector import Vector

pytestmark = pytest.mark.db


async def test_vector_codec_round_trips(db):
    async with db.acquire() as conn:
        value = await conn.fetchval("select $1::extensions.vector", [1.0, 2.0, 3.0])

    assert isinstance(value, Vector)
    assert value.to_list() == [1.0, 2.0, 3.0]


async def test_search_path_survives_release(db):
    # Releasing a connection runs RESET ALL; the pool must restore its search_path.
    async with db.acquire() as conn:
        first_pid = conn.get_server_pid()
        assert await conn.fetchval("select current_setting('search_path')") == "public, extensions"
        await conn.execute("set search_path to public")

    async with db.acquire() as conn:
        assert conn.get_server_pid() == first_pid  # the same pooled connection, reset
        assert await conn.fetchval("select current_setting('search_path')") == "public, extensions"
        value = await conn.fetchval("select '[1,2]'::vector")

    assert value.to_list() == [1.0, 2.0]


async def test_transaction_yields_connection_in_transaction(db):
    async with db.transaction() as conn:
        assert conn.is_in_transaction()


async def test_transaction_propagates_errors(db):
    with pytest.raises(RuntimeError, match="boom"):
        async with db.transaction():
            raise RuntimeError("boom")

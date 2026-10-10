"""asyncpg connection pool for the Supabase Postgres database."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from pgvector.asyncpg import register_vector

# Supabase installs pgvector into the `extensions` schema, not `public`.
EXTENSIONS_SCHEMA = "extensions"
SET_SEARCH_PATH = f"SET search_path TO public, {EXTENSIONS_SCHEMA};"


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Runs once per new pooled connection: vector columns map to `pgvector.Vector`."""
    await register_vector(conn, schema=EXTENSIONS_SCHEMA)
    await conn.execute(SET_SEARCH_PATH)


async def _reset_connection(conn: asyncpg.Connection) -> None:
    """Runs on release: the default reset ends in RESET ALL, so restore the search_path.

    A SET (rather than a startup parameter) works the same through the Supavisor
    pooler as on a direct connection.
    """
    await conn.execute(conn.get_reset_query() + "\n" + SET_SEARCH_PATH)


class Database:
    """Owns the asyncpg pool.

    The backend connects with privileged credentials, so row-level security does
    not apply to these connections: callers must enforce ownership in code.
    """

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def connect(self, dsn: str, *, min_size: int = 1, max_size: int = 10) -> None:
        if self._pool is not None:
            raise RuntimeError("Database is already connected")
        self._pool = await asyncpg.create_pool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            init=_init_connection,
            reset=_reset_connection,
        )

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.close()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        if self._pool is None:
            raise RuntimeError("Database is not connected")
        async with self._pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """A connection inside a transaction: committed on exit, rolled back on error."""
        async with self.acquire() as conn, conn.transaction():
            yield conn

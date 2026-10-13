"""Applies one migration file to the database at SUPABASE_DB_URL.

    uv run python -m scripts.apply_migration supabase/migrations/<version>_<name>.sql

The whole file runs in one transaction, so a failure applies nothing. When the Supabase
migration history table (`supabase_migrations.schema_migrations`) exists, the version is
recorded there afterwards, as `supabase db push` would; a version that is already recorded
is refused.
"""

import asyncio
import re
import sys
from pathlib import Path

import asyncpg

from app.config import get_settings

FILENAME = re.compile(r"^(?P<version>\d{14})_(?P<name>[A-Za-z0-9_]+)\.sql$")

HISTORY_TABLE_EXISTS = "select to_regclass('supabase_migrations.schema_migrations') is not null"
VERSION_RECORDED = (
    "select exists (select 1 from supabase_migrations.schema_migrations where version = $1)"
)
RECORD_VERSION = """
insert into supabase_migrations.schema_migrations (version, name)
values ($1, $2)
on conflict do nothing
"""


class MigrationError(Exception):
    """The migration cannot be applied; the message says why."""


def parse_filename(path: Path) -> tuple[str, str]:
    """The `(version, name)` of `<14-digit version>_<name>.sql`."""
    match = FILENAME.match(path.name)
    if match is None:
        raise MigrationError(f"{path.name}: expected a file named <14-digit version>_<name>.sql")
    return match["version"], match["name"]


async def apply_migration(dsn: str, path: Path) -> None:
    version, name = parse_filename(path)
    sql = path.read_text(encoding="utf-8")
    # statement_cache_size=0 keeps the connection usable behind a transaction-mode pooler.
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        has_history = await conn.fetchval(HISTORY_TABLE_EXISTS)
        if has_history and await conn.fetchval(VERSION_RECORDED, version):
            raise MigrationError(f"{path.name}: version {version} is already applied")
        async with conn.transaction():
            await conn.execute(sql)
            if has_history:
                await conn.execute(RECORD_VERSION, version, name)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m scripts.apply_migration supabase/migrations/<file>.sql")
        return 1
    path = Path(args[0])
    settings = get_settings()
    if not settings.database_configured:
        print("SUPABASE_DB_URL is empty or still the dashboard placeholder; set it in backend/.env")
        return 1
    if not path.is_file():
        print(f"{path}: no such file")
        return 1
    try:
        asyncio.run(apply_migration(settings.supabase_db_url, path))
    except MigrationError as exc:
        print(exc)
        return 1
    print(f"Applied {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

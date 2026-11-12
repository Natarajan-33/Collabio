"""Remove test leftovers from the shared demo accounts, keeping the money demo.

Tests and the public demo share one Supabase project and the same demo brand and creators, so
test runs leave briefs, batches, threads and deals behind (an extra "Lumen Pods" deal, a
cluttered Board). This deletes, for the demo brand only:
- every brief not tagged `collabio-demo-money` (cascading to its batches, threads, deals and
  money rows);
and, only with `--include-other-brands`, threads to the demo creators (Priya, Arjun) from any
other brand (such a brand may be a real account, so it is reported, not deleted, by default).

Creators, packages, logins and the money demo's own briefs are kept. Run `scripts.seed_money`
afterwards.

Usage (from backend/):
  uv run python -m scripts.clean_demo            # dry run: counts only
  uv run python -m scripts.clean_demo --apply    # delete
  uv run python -m scripts.clean_demo --apply --include-other-brands
"""

import asyncio
import sys

import asyncpg

from app.config import get_settings
from scripts.seed import ARJUN_HANDLE
from scripts.seed_money import MARKER

COUNTS = {
    "briefs": "select count(*) from public.briefs where brand_id = $1"
    " and flexibility_note is distinct from $2",
    "batches": "select count(*) from public.batches b join public.briefs br on br.id = b.brief_id"
    " where br.brand_id = $1 and br.flexibility_note is distinct from $2",
    "threads": "select count(*) from public.threads t join public.batches b on b.id = t.batch_id"
    " join public.briefs br on br.id = b.brief_id"
    " where br.brand_id = $1 and br.flexibility_note is distinct from $2",
    "deals": "select count(*) from public.deals d join public.batches b on b.id = d.batch_id"
    " join public.briefs br on br.id = b.brief_id"
    " where br.brand_id = $1 and br.flexibility_note is distinct from $2",
}


async def _ids(conn: asyncpg.Connection) -> tuple:
    s = get_settings()
    brand_id = await conn.fetchval(
        "select b.id from public.brands b join auth.users u on u.id = b.profile_id"
        " where u.email = $1",
        s.demo_brand_email,
    )
    creators = await conn.fetch(
        "select c.id from public.creators c left join auth.users u on u.id = c.profile_id"
        " where u.email = $1 or c.handle = $2",
        s.demo_helper_email,
        ARJUN_HANDLE,
    )
    return brand_id, [r["id"] for r in creators]


async def clean(
    conn: asyncpg.Connection, apply: bool, other_brands: bool = False
) -> dict[str, int]:
    brand_id, creator_ids = await _ids(conn)
    if brand_id is None:
        raise RuntimeError("demo brand not found")
    report = {k: await conn.fetchval(q, brand_id, MARKER) for k, q in COUNTS.items()}
    report["other_brand_threads_to_demo_creators"] = await conn.fetchval(
        "select count(*) from public.threads where creator_id = any($1::uuid[]) and brand_id <> $2",
        creator_ids,
        brand_id,
    )
    if apply:
        async with conn.transaction():
            await conn.execute("set local collabio.demo_reset = 'on'")
            await conn.execute(
                "delete from public.briefs where brand_id = $1"
                " and flexibility_note is distinct from $2",
                brand_id,
                MARKER,
            )
            if other_brands:
                await conn.execute(
                    "delete from public.threads where creator_id = any($1::uuid[])"
                    " and brand_id <> $2",
                    creator_ids,
                    brand_id,
                )
    return report


async def main() -> None:
    apply = "--apply" in sys.argv
    conn = await asyncpg.connect(get_settings().supabase_db_url, statement_cache_size=0)
    try:
        report = await clean(conn, apply, "--include-other-brands" in sys.argv)
    finally:
        await conn.close()
    print(("deleted" if apply else "would delete (dry run)"), report)


if __name__ == "__main__":
    asyncio.run(main())

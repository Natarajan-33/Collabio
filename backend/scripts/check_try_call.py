"""Quick check for Try it yourself prerequisites (no secrets printed)."""

import asyncio
import sys

from app.adapters.db import Database
from app.config import get_settings


async def main() -> int:
    s = get_settings()
    ok = True
    for name, present in [
        ("ELEVENLABS_API_KEY", bool(s.elevenlabs_api_key)),
        ("ELEVENLABS_NEGOTIATION_AGENT_ID", bool(s.elevenlabs_negotiation_agent_id)),
        ("ELEVENLABS_PHONE_NUMBER_ID", bool(s.elevenlabs_phone_number_id)),
    ]:
        print(f"{name}: {'OK' if present else 'MISSING'}")
        ok &= present

    if not s.database_configured:
        print("SUPABASE_DB_URL: MISSING or placeholder")
        return 1

    db = Database()
    await db.connect(s.supabase_db_url)
    try:
        async with db.acquire() as conn:
            lumen = await conn.fetchval(
                "select id from public.brands where company_name = $1 limit 1", "Lumen Audio"
            )
            arjun = await conn.fetchval(
                "select id from public.creators where handle = $1 limit 1", "arjuntech"
            )
            print(f"Seeded Lumen Audio brand: {'OK' if lumen else 'MISSING (run: uv run python -m scripts.seed)'}")
            print(f"Seeded arjuntech creator: {'OK' if arjun else 'MISSING (run seed)'}")
            ok &= bool(lumen and arjun)
    finally:
        await db.close()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

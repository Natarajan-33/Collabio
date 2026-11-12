"""Money demo seed (spec §9): four fictional deals between Lumen Audio and two creators.

Priya Raman (the creator persona):
1. "Lumen Pods launch": booked and unfunded. The live judge path funds it, submits proof
   and gets paid, so only this deal moves real sandbox money.
2. "Studio Monitors": funded, one video paid, one payout waiting for approval.
Arjun Mehta (a second creator, so the dashboard compares cost per 1K views):
3. "Desk Speaker": completed, with the unspent budget refunded.
4. "Soundbar review": funded, one video paid on 1.5M views, one still to come.

Historic rows of deals 2-4 carry `SEED-` PayPal references and `{"seed": true}` payloads.
Re-running deletes the demo deals (through their briefs) and recreates them.

    uv run python -m scripts.seed_money
"""

import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from app.config import get_settings
from scripts.seed import ARJUN_HANDLE

MARKER = "collabio-demo-money"
DEMO_TITLES = ("Lumen Pods launch", "Studio Monitors", "Desk Speaker", "Soundbar review")
STUDIO_TERMS = {
    "cpm": {"rate_cents_per_1k": 200, "starts_after_views": 200_000, "cap_cents": 50_000},
    "tiers": [{"views": 1_000_000, "bonus_cents": 30_000}],
}
SOUNDBAR_TERMS = {
    "cpm": {"rate_cents_per_1k": 100, "starts_after_views": 300_000, "cap_cents": 60_000},
    "tiers": [],
}
SEED = {"seed": True}

DEALS = [
    {
        "title": "Lumen Pods launch",
        "product": "Lumen Pods",
        "summary": "Wireless earbuds with a 30-hour battery and crisp call quality.",
        "conditions": ["Show the charging case on camera", "Mention the 30-hour battery"],
        "amounts": [40_000, 40_000],
        "go_live_days": 21,
        "creator": "priya",
    },
    {
        "title": "Studio Monitors",
        "product": "Lumen Studio Monitors",
        "summary": "Compact studio speakers for home producers.",
        "conditions": ["Play a short track through them", "Link the product page"],
        "amounts": [60_000, 60_000],
        "go_live_days": 14,
        "creator": "priya",
    },
    {
        "title": "Desk Speaker",
        "product": "Lumen Desk Speaker",
        "summary": "A small Bluetooth speaker for desks and dorms.",
        "conditions": ["Show it in a desk setup"],
        "amounts": [70_000],
        "go_live_days": -20,
        "creator": "arjun",
    },
    {
        "title": "Soundbar review",
        "product": "Lumen Soundbar",
        "summary": "A slim TV soundbar with a wireless subwoofer.",
        "conditions": ["Compare TV speakers with the soundbar", "Show the setup in under a minute"],
        "amounts": [50_000, 50_000],
        "go_live_days": 10,
        "creator": "arjun",
    },
]


async def _party_ids(conn: asyncpg.Connection) -> tuple[UUID, dict[str, tuple[UUID, UUID]]]:
    """The demo brand, and each demo creator's id and first package (Priya, Arjun)."""
    settings = get_settings()
    brand_id = await conn.fetchval(
        "select b.id from public.brands b join auth.users u on u.id = b.profile_id"
        " where u.email = $1",
        settings.demo_brand_email,
    )
    priya = await conn.fetchval(
        "select c.id from public.creators c join auth.users u on u.id = c.profile_id"
        " where u.email = $1",
        settings.demo_helper_email,
    )
    arjun = await conn.fetchval("select id from public.creators where handle = $1", ARJUN_HANDLE)
    if brand_id is None or priya is None or arjun is None:
        raise RuntimeError("Run scripts.seed first: the demo brand or creators are missing")
    creators = {}
    for key, creator_id in (("priya", priya), ("arjun", arjun)):
        package_id = await conn.fetchval(
            "select id from public.packages where creator_id = $1 order by updated_at limit 1",
            creator_id,
        )
        creators[key] = (creator_id, package_id)
    return brand_id, creators


async def _event(conn, deal_id, kind, cents, ref=None, payload=None) -> None:
    await conn.execute(
        "insert into public.money_events (deal_id, kind, amount_cents, paypal_ref, payload)"
        " values ($1, $2, $3, $4, $5::jsonb)",
        deal_id,
        kind,
        cents,
        ref,
        json.dumps({**SEED, **(payload or {})}),
    )


async def _submission(conn, milestone_id, views, summary) -> UUID:
    return await conn.fetchval(
        "insert into public.milestone_submissions (milestone_id, post_url, caption,"
        " claimed_views, screenshot_path, status, brief_ok, disclosure_ok, views,"
        " view_confidence, agent_summary) values ($1, 'https://example.com/p/seed',"
        " 'Seeded demo post #ad', $2, 'seed/none.png', 'verified', true, true, $2, 'high', $3)"
        " returning id",
        milestone_id,
        views,
        summary,
    )


async def _payout(conn, milestone_id, submission_id, cents, status, breakdown) -> UUID:
    return await conn.fetchval(
        "insert into public.payouts (milestone_id, submission_id, amount_cents, breakdown,"
        " status, sender_batch_id, paypal_batch_id, paypal_item_id) values"
        " ($1, $2, $3, $4::jsonb, $5, 'SEED-' || gen_random_uuid(),"
        " case when $5 = 'success' then 'SEED-BATCH-' || substr(md5(random()::text), 1, 8) end,"
        " case when $5 = 'success' then 'SEED-ITEM-' || substr(md5(random()::text), 1, 8) end)"
        " returning id",
        milestone_id,
        submission_id,
        cents,
        json.dumps({**breakdown, "reason": "Seeded demo payout"}),
        status,
    )


async def _create_deal(conn, brand_id, creator_id, package_id, spec) -> tuple[UUID, list[UUID]]:
    today = datetime.now(UTC).date()
    go_live = today + timedelta(days=spec["go_live_days"])
    brief_id = await conn.fetchval(
        "insert into public.briefs (brand_id, status, brand_name, product_name, product_summary,"
        " deliverables_count, deliverables_format, go_live_by, flexibility_note, ask_price_cents)"
        " values ($1, 'launched', 'Lumen Audio', $2, $3, $4, 'short_video', $5, $6, $7)"
        " returning id",
        brand_id,
        spec["product"],
        spec["summary"],
        len(spec["amounts"]),
        go_live,
        MARKER,
        sum(spec["amounts"]),
    )
    batch_id = await conn.fetchval(
        "insert into public.batches (brief_id, brand_id) values ($1, $2) returning id",
        brief_id,
        brand_id,
    )
    thread_id = await conn.fetchval(
        "insert into public.threads (batch_id, brand_id, creator_id, package_id, channel_plan,"
        " status, reply_token) values ($1, $2, $3, $4, 'email', 'awarded', $5) returning id",
        batch_id,
        brand_id,
        creator_id,
        package_id,
        secrets.token_urlsafe(24),
    )
    event_id = await conn.fetchval(
        "insert into public.thread_events (thread_id, batch_id, brand_id, creator_id, type,"
        " actor, payload) values ($1, $2, $3, $4, 'awarded', 'brand', '{}'::jsonb) returning id",
        thread_id,
        batch_id,
        brand_id,
        creator_id,
    )
    deal_id = await conn.fetchval(
        "insert into public.deals (thread_id, batch_id, brand_id, creator_id, package_id, videos,"
        " format, price_cents, go_live_by, conditions, awarded_event_id) values"
        " ($1, $2, $3, $4, $5, $6, 'short_video', $7, $8, $9, $10) returning id",
        thread_id,
        batch_id,
        brand_id,
        creator_id,
        package_id,
        len(spec["amounts"]),
        sum(spec["amounts"]),
        go_live,
        spec["conditions"],
        event_id,
    )
    milestone_ids = []
    for seq, amount in enumerate(spec["amounts"], start=1):
        milestone_ids.append(
            await conn.fetchval(
                "insert into public.deal_milestones (deal_id, seq, title, amount_cents, due_date)"
                " values ($1, $2, $3, $4, $5) returning id",
                deal_id,
                seq,
                f"Video {seq}",
                amount,
                go_live,
            )
        )
    return deal_id, milestone_ids


async def _fund(conn, deal_id, amount, milestone_ids) -> None:
    await conn.execute(
        "insert into public.deal_funding (deal_id, paypal_order_id, capture_id, amount_cents,"
        " status, captured_at) values ($1, 'SEED-ORDER-' || substr(md5(random()::text), 1, 8),"
        " 'SEED-CAP-' || substr(md5(random()::text), 1, 8), $2, 'captured', now())",
        deal_id,
        amount,
    )
    await conn.execute("update public.deals set status = 'funded' where id = $1", deal_id)
    await conn.execute(
        "update public.deal_milestones set status = 'funded' where id = any($1::uuid[])",
        milestone_ids,
    )
    await _event(conn, deal_id, "funded", amount, "SEED-CAPTURE")


async def seed_money(conn: asyncpg.Connection) -> dict[str, UUID]:
    """(Re)create the demo deals; returns their ids by title."""
    brand_id, creators = await _party_ids(conn)
    settings = get_settings()
    async with conn.transaction():
        await conn.execute("set local collabio.demo_reset = 'on'")
        await conn.execute(
            "delete from public.briefs where brand_id = $1 and flexibility_note = $2",
            brand_id,
            MARKER,
        )
        # $500 auto-approve: a $400 base pays itself; bonus-heavy payouts wait for the brand.
        await conn.execute(
            "update public.brands set auto_approve_limit_cents = 50000 where id = $1", brand_id
        )
        if settings.paypal_receiver_email:
            await conn.execute(
                "update public.creators set payout_email = $2 where id = any($1::uuid[])",
                [c for c, _ in creators.values()],
                settings.paypal_receiver_email,
            )
        ids: dict[str, UUID] = {}
        for spec in DEALS:
            creator_id, package_id = creators[spec["creator"]]
            deal_id, milestones = await _create_deal(conn, brand_id, creator_id, package_id, spec)
            ids[spec["title"]] = deal_id

            if spec["title"] == "Studio Monitors":
                await conn.execute(
                    "insert into public.deal_bonus_terms (deal_id, source_text, terms,"
                    " max_bonus_per_video_cents) values ($1, $2, $3::jsonb, 80000)",
                    deal_id,
                    "$2 per 1K views after 200K, up to $500 per video, +$300 at 1M views",
                    json.dumps(STUDIO_TERMS),
                )
                await _fund(conn, deal_id, 120_000 + 2 * 80_000, milestones)
                s1 = await _submission(conn, milestones[0], 812_400, "On brief, #ad shown.")
                p1 = await _payout(
                    conn,
                    milestones[0],
                    s1,
                    110_000,
                    "success",
                    {
                        "base": 60_000,
                        "cpm": 50_000,
                        "tiers": 0,
                        "already_committed": 0,
                        "delta": 110_000,
                    },
                )
                await conn.execute(
                    "update public.deal_milestones set status = 'paid' where id = $1",
                    milestones[0],
                )
                for kind in ("payout_queued", "payout_sent", "payout_succeeded"):
                    await _event(
                        conn, deal_id, kind, 110_000, f"SEED-{kind.upper()}", {"payout_id": str(p1)}
                    )
                s2 = await _submission(
                    conn, milestones[1], 1_240_000, "On brief; 1.24M views read from analytics."
                )
                p2 = await _payout(
                    conn,
                    milestones[1],
                    s2,
                    140_000,
                    "awaiting_approval",
                    {
                        "base": 60_000,
                        "cpm": 50_000,
                        "tiers": 30_000,
                        "already_committed": 0,
                        "delta": 140_000,
                    },
                )
                await conn.execute(
                    "update public.deal_milestones set status = 'verified' where id = $1",
                    milestones[1],
                )
                await _event(
                    conn,
                    deal_id,
                    "payout_queued",
                    140_000,
                    None,
                    {"payout_id": str(p2), "decision": "approval"},
                )

            if spec["title"] == "Soundbar review":
                await conn.execute(
                    "insert into public.deal_bonus_terms (deal_id, source_text, terms,"
                    " max_bonus_per_video_cents) values ($1, $2, $3::jsonb, 60000)",
                    deal_id,
                    "$1 per 1K views after 300K, up to $600 per video",
                    json.dumps(SOUNDBAR_TERMS),
                )
                await _fund(conn, deal_id, 100_000 + 2 * 60_000, milestones)
                s1 = await _submission(
                    conn, milestones[0], 1_500_000, "On brief; 1.5M views read from analytics."
                )
                p1 = await _payout(
                    conn,
                    milestones[0],
                    s1,
                    110_000,
                    "success",
                    {
                        "base": 50_000,
                        "cpm": 60_000,
                        "tiers": 0,
                        "already_committed": 0,
                        "delta": 110_000,
                    },
                )
                await conn.execute(
                    "update public.deal_milestones set status = 'paid' where id = $1",
                    milestones[0],
                )
                for kind in ("payout_queued", "payout_sent", "payout_succeeded"):
                    await _event(
                        conn, deal_id, kind, 110_000, f"SEED-{kind.upper()}", {"payout_id": str(p1)}
                    )

            if spec["title"] == "Desk Speaker":
                await _fund(conn, deal_id, 100_000, milestones)
                s1 = await _submission(conn, milestones[0], 420_000, "On brief, #ad shown.")
                p1 = await _payout(
                    conn,
                    milestones[0],
                    s1,
                    70_000,
                    "success",
                    {"base": 70_000, "cpm": 0, "tiers": 0, "already_committed": 0, "delta": 70_000},
                )
                await conn.execute(
                    "update public.deal_milestones set status = 'paid' where id = $1",
                    milestones[0],
                )
                for kind in ("payout_queued", "payout_sent", "payout_succeeded"):
                    await _event(
                        conn, deal_id, kind, 70_000, f"SEED-{kind.upper()}", {"payout_id": str(p1)}
                    )
                await conn.execute(
                    "update public.deal_funding set refunded_cents = 30000 where deal_id = $1",
                    deal_id,
                )
                await _event(conn, deal_id, "refunded", 30_000, "SEED-REFUND")
                await conn.execute(
                    "update public.deals set status = 'completed' where id = $1", deal_id
                )
    return ids


async def main() -> None:
    conn = await asyncpg.connect(get_settings().supabase_db_url, statement_cache_size=0)
    try:
        ids = await seed_money(conn)
        for title, deal_id in ids.items():
            print(f"{title}: {deal_id}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

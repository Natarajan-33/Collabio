"""Data access for M4 money. Every query takes a connection; callers own transactions."""

import json
from typing import Any
from uuid import UUID

import asyncpg


async def brand_deal(conn: asyncpg.Connection, deal_id: UUID, brand_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        "select * from public.deals where id = $1 and brand_id = $2", deal_id, brand_id
    )
    return None if row is None else dict(row)


async def party_deal(
    conn: asyncpg.Connection, deal_id: UUID, *, brand_id: UUID | None, creator_id: UUID | None
) -> dict | None:
    row = await conn.fetchrow(
        "select * from public.deals where id = $1 and (brand_id = $2 or creator_id = $3)",
        deal_id,
        brand_id,
        creator_id,
    )
    return None if row is None else dict(row)


async def milestones(conn: asyncpg.Connection, deal_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "select * from public.deal_milestones where deal_id = $1 order by seq", deal_id
    )
    return [dict(r) for r in rows]


async def bonus_terms(conn: asyncpg.Connection, deal_id: UUID) -> dict | None:
    row = await conn.fetchrow("select * from public.deal_bonus_terms where deal_id = $1", deal_id)
    if row is None:
        return None
    out = dict(row)
    if isinstance(out["terms"], str):
        out["terms"] = json.loads(out["terms"])
    return out


async def upsert_bonus_terms(
    conn: asyncpg.Connection,
    deal_id: UUID,
    source_text: str,
    terms: dict[str, Any],
    max_bonus_per_video_cents: int,
) -> None:
    await conn.execute(
        "insert into public.deal_bonus_terms (deal_id, source_text, terms, max_bonus_per_video_cents)"
        " values ($1, $2, $3::jsonb, $4)"
        " on conflict (deal_id) do update set source_text = excluded.source_text,"
        " terms = excluded.terms, max_bonus_per_video_cents = excluded.max_bonus_per_video_cents,"
        " created_at = now()",
        deal_id,
        source_text,
        json.dumps(terms),
        max_bonus_per_video_cents,
    )


async def set_auto_approve_limit(conn: asyncpg.Connection, brand_id: UUID, cents: int) -> None:
    await conn.execute(
        "update public.brands set auto_approve_limit_cents = $2 where id = $1", brand_id, cents
    )


async def auto_approve_limit(conn: asyncpg.Connection, brand_id: UUID) -> int:
    return await conn.fetchval(
        "select auto_approve_limit_cents from public.brands where id = $1", brand_id
    )


LIVE_PAYOUT = ("awaiting_approval", "approved", "sent", "success")


def _row(r) -> dict:
    out = dict(r)
    for key in ("payload", "breakdown", "transcript", "last_error"):
        if isinstance(out.get(key), str):
            out[key] = json.loads(out[key])
    return out


async def funding(conn: asyncpg.Connection, deal_id: UUID, *, lock: bool = False) -> dict | None:
    sql = "select * from public.deal_funding where deal_id = $1" + (" for update" if lock else "")
    row = await conn.fetchrow(sql, deal_id)
    return None if row is None else dict(row)


async def upsert_created_order(
    conn: asyncpg.Connection, deal_id: UUID, order_id: str, amount_cents: int
) -> bool:
    """Record a new order; False (and no change) once the deal's funding is captured."""
    changed = await conn.fetchval(
        "insert into public.deal_funding (deal_id, paypal_order_id, amount_cents, status)"
        " values ($1, $2, $3, 'created')"
        " on conflict (deal_id) do update set paypal_order_id = excluded.paypal_order_id,"
        " amount_cents = excluded.amount_cents, status = 'created'"
        " where public.deal_funding.status <> 'captured'"
        " returning deal_id",
        deal_id,
        order_id,
        amount_cents,
    )
    return changed is not None


async def mark_captured(conn: asyncpg.Connection, deal_id: UUID, capture_id: str) -> None:
    await conn.execute(
        "update public.deal_funding set status = 'captured', capture_id = $2, captured_at = now()"
        " where deal_id = $1",
        deal_id,
        capture_id,
    )
    await conn.execute("update public.deals set status = 'funded' where id = $1", deal_id)
    await conn.execute(
        "update public.deal_milestones set status = 'funded' where deal_id = $1"
        " and status = 'pending'",
        deal_id,
    )


async def mark_funding_failed(conn: asyncpg.Connection, deal_id: UUID) -> None:
    await conn.execute(
        "update public.deal_funding set status = 'failed' where deal_id = $1", deal_id
    )


async def add_event(
    conn: asyncpg.Connection,
    deal_id: UUID,
    kind: str,
    amount_cents: int,
    paypal_ref: str | None = None,
    payload: dict | None = None,
) -> None:
    await conn.execute(
        "insert into public.money_events (deal_id, kind, amount_cents, paypal_ref, payload)"
        " values ($1, $2, $3, $4, $5::jsonb)",
        deal_id,
        kind,
        amount_cents,
        paypal_ref,
        json.dumps(payload or {}),
    )


async def ledger(conn: asyncpg.Connection, deal_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "select * from public.money_events where deal_id = $1 order by id", deal_id
    )
    return [_row(r) for r in rows]


async def submissions_for_deal(conn: asyncpg.Connection, deal_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "select s.*, r.status as run_status from public.milestone_submissions s"
        " join public.deal_milestones m on m.id = s.milestone_id"
        " left join public.settlement_runs r on r.submission_id = s.id"
        " where m.deal_id = $1 order by s.created_at desc",
        deal_id,
    )
    return [_row(r) for r in rows]


async def creator_milestone(
    conn: asyncpg.Connection, milestone_id: UUID, creator_id: UUID
) -> dict | None:
    row = await conn.fetchrow(
        "select m.*, d.status as deal_status, d.id as deal_id from public.deal_milestones m"
        " join public.deals d on d.id = m.deal_id where m.id = $1 and d.creator_id = $2",
        milestone_id,
        creator_id,
    )
    return None if row is None else dict(row)


async def insert_submission(
    conn: asyncpg.Connection,
    milestone_id: UUID,
    post_url: str,
    caption: str,
    claimed_views: int,
    screenshot_path: str,
) -> UUID:
    return await conn.fetchval(
        "insert into public.milestone_submissions (milestone_id, post_url, caption,"
        " claimed_views, screenshot_path) values ($1, $2, $3, $4, $5) returning id",
        milestone_id,
        post_url,
        caption,
        claimed_views,
        screenshot_path,
    )


async def set_milestone_status(conn: asyncpg.Connection, milestone_id: UUID, status: str) -> None:
    await conn.execute(
        "update public.deal_milestones set status = $2 where id = $1", milestone_id, status
    )


async def submission_context(conn: asyncpg.Connection, submission_id: UUID) -> dict | None:
    """The submission with its milestone, deal, brief, creator and brand settings."""
    row = await conn.fetchrow(
        "select s.id as submission_id, s.post_url, s.caption, s.claimed_views,"
        " s.screenshot_path, s.status as submission_status,"
        " m.id as milestone_id, m.seq, m.title, m.amount_cents, m.status as milestone_status,"
        " d.id as deal_id, d.status as deal_status, d.videos, d.format, d.conditions,"
        " d.go_live_by, d.brand_id, d.creator_id,"
        " br.product_name, br.product_summary, br.brand_name, br.deliverable_length_s,"
        " c.payout_email, c.name as creator_name,"
        " b.auto_approve_limit_cents"
        " from public.milestone_submissions s"
        " join public.deal_milestones m on m.id = s.milestone_id"
        " join public.deals d on d.id = m.deal_id"
        " join public.batches ba on ba.id = d.batch_id"
        " join public.briefs br on br.id = ba.brief_id"
        " join public.creators c on c.id = d.creator_id"
        " join public.brands b on b.id = d.brand_id"
        " where s.id = $1",
        submission_id,
    )
    return None if row is None else dict(row)


async def claim_run(conn: asyncpg.Connection, submission_id: UUID) -> bool:
    """Start (or restart after an error) the one settlement run of a submission. False when
    a run is already going or finished."""
    inserted = await conn.fetchval(
        "insert into public.settlement_runs (submission_id) values ($1)"
        " on conflict (submission_id) do nothing returning id",
        submission_id,
    )
    if inserted is not None:
        return True
    restarted = await conn.fetchval(
        "update public.settlement_runs set status = 'running', error = null,"
        " started_at = now(), finished_at = null"
        " where submission_id = $1 and (status = 'error'"
        " or (status = 'running' and started_at < now() - interval '5 minutes')) returning id",
        submission_id,
    )
    return restarted is not None


async def finish_run(
    conn: asyncpg.Connection,
    submission_id: UUID,
    status: str,
    transcript: list,
    error: str | None = None,
) -> None:
    await conn.execute(
        "update public.settlement_runs set status = $2, transcript = $3::jsonb, error = $4,"
        " finished_at = now() where submission_id = $1",
        submission_id,
        status,
        json.dumps(transcript, default=str),
        error,
    )


async def record_verification(
    conn: asyncpg.Connection,
    submission_id: UUID,
    *,
    brief_ok: bool,
    disclosure_ok: bool,
    missing_points: list[str],
    views: int,
    view_confidence: str,
    summary: str,
) -> None:
    await conn.execute(
        "update public.milestone_submissions set status = 'verified', brief_ok = $2,"
        " disclosure_ok = $3, missing_points = $4, views = $5, view_confidence = $6,"
        " agent_summary = $7 where id = $1",
        submission_id,
        brief_ok,
        disclosure_ok,
        missing_points,
        max(0, views),
        view_confidence,
        summary[:2000],
    )


async def request_changes(conn: asyncpg.Connection, submission_id: UUID, message: str) -> None:
    await conn.execute(
        "update public.milestone_submissions set status = 'needs_changes', agent_summary = $2"
        " where id = $1",
        submission_id,
        message[:2000],
    )


async def lock_milestone(conn: asyncpg.Connection, milestone_id: UUID) -> dict:
    return dict(
        await conn.fetchrow(
            "select * from public.deal_milestones where id = $1 for update", milestone_id
        )
    )


async def milestone_submissions(conn: asyncpg.Connection, milestone_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "select * from public.milestone_submissions where milestone_id = $1", milestone_id
    )
    return [_row(r) for r in rows]


async def milestone_payouts(conn: asyncpg.Connection, milestone_id: UUID) -> list[dict]:
    rows = await conn.fetch("select * from public.payouts where milestone_id = $1", milestone_id)
    return [_row(r) for r in rows]


async def deal_committed(conn: asyncpg.Connection, deal_id: UUID) -> int:
    return await conn.fetchval(
        "select coalesce(sum(p.amount_cents), 0) from public.payouts p"
        " join public.deal_milestones m on m.id = p.milestone_id"
        " where m.deal_id = $1 and p.status = any($2::text[])",
        deal_id,
        list(LIVE_PAYOUT),
    )


async def insert_payout(
    conn: asyncpg.Connection,
    milestone_id: UUID,
    submission_id: UUID | None,
    amount_cents: int,
    breakdown: dict,
    status: str,
) -> UUID:
    payout_id = await conn.fetchval(
        "insert into public.payouts (milestone_id, submission_id, amount_cents, breakdown,"
        " status, sender_batch_id) values ($1, $2, $3, $4::jsonb, $5,"
        " 'collabio-' || gen_random_uuid()) returning id",
        milestone_id,
        submission_id,
        amount_cents,
        json.dumps(breakdown),
        status,
    )
    await conn.execute(
        "update public.payouts set sender_batch_id = 'collabio-' || id::text where id = $1",
        payout_id,
    )
    return payout_id


async def payout(conn: asyncpg.Connection, payout_id: UUID, *, lock: bool = False) -> dict | None:
    sql = "select * from public.payouts where id = $1" + (" for update" if lock else "")
    row = await conn.fetchrow(sql, payout_id)
    return None if row is None else _row(row)


async def update_payout(conn: asyncpg.Connection, payout_id: UUID, **fields: Any) -> None:
    cols = list(fields)
    sets = ", ".join(
        f"{c} = ${i + 2}{'::jsonb' if c in ('last_error', 'breakdown') else ''}"
        for i, c in enumerate(cols)
    )
    values = [
        json.dumps(fields[c]) if c in ("last_error", "breakdown") else fields[c] for c in cols
    ]
    await conn.execute(
        f"update public.payouts set {sets}, updated_at = now() where id = $1", payout_id, *values
    )


async def payouts_for_deal(conn: asyncpg.Connection, deal_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "select p.* from public.payouts p join public.deal_milestones m on m.id = p.milestone_id"
        " where m.deal_id = $1 order by p.created_at desc",
        deal_id,
    )
    return [_row(r) for r in rows]


async def payout_with_deal(
    conn: asyncpg.Connection, payout_id: UUID, *, lock: bool = False
) -> dict | None:
    """The payout with its milestone and deal ids, the deal's brand and status."""
    sql = (
        "select p.*, m.deal_id, d.brand_id, d.status as deal_status from public.payouts p"
        " join public.deal_milestones m on m.id = p.milestone_id"
        " join public.deals d on d.id = m.deal_id where p.id = $1"
    ) + (" for update of p" if lock else "")
    row = await conn.fetchrow(sql, payout_id)
    return None if row is None else _row(row)


async def payout_by_paypal_ref(conn: asyncpg.Connection, ref: str) -> UUID | None:
    return await conn.fetchval(
        "select id from public.payouts where paypal_item_id = $1 or paypal_batch_id = $1"
        " or sender_batch_id = $1 limit 1",
        ref,
    )


async def sent_payout_ids(conn: asyncpg.Connection, limit: int = 50) -> list[UUID]:
    rows = await conn.fetch(
        "select id from public.payouts where status = 'sent' order by random() limit $1", limit
    )
    return [r["id"] for r in rows]


async def reject_awaiting_for_deal(conn: asyncpg.Connection, deal_id: UUID, reason: str) -> int:
    rows = await conn.fetch(
        "update public.payouts p set status = 'rejected', reject_reason = $2, updated_at = now()"
        " from public.deal_milestones m where m.id = p.milestone_id and m.deal_id = $1"
        " and p.status = 'awaiting_approval' returning p.id",
        deal_id,
        reason,
    )
    return len(rows)


async def add_refund(conn: asyncpg.Connection, deal_id: UUID, cents: int) -> None:
    await conn.execute(
        "update public.deal_funding set refunded_cents = refunded_cents + $2 where deal_id = $1",
        deal_id,
        cents,
    )


async def set_deal_status(conn: asyncpg.Connection, deal_id: UUID, status: str) -> None:
    await conn.execute("update public.deals set status = $2 where id = $1", deal_id, status)


async def stale_error_runs(conn: asyncpg.Connection, older_than_minutes: int = 10) -> list[UUID]:
    rows = await conn.fetch(
        "select r.submission_id from public.settlement_runs r"
        " join public.milestone_submissions s on s.id = r.submission_id"
        " where s.status = 'submitted' and ((r.status = 'error'"
        " and r.finished_at < now() - make_interval(mins => $1))"
        " or (r.status = 'running' and r.started_at < now() - interval '5 minutes')) limit 20",
        older_than_minutes,
    )
    return [r["submission_id"] for r in rows]


async def deal_status(conn: asyncpg.Connection, deal_id: UUID) -> str:
    return await conn.fetchval("select status from public.deals where id = $1", deal_id)


async def stale_approved_payout_ids(conn: asyncpg.Connection, min_age_seconds: int) -> list[UUID]:
    rows = await conn.fetch(
        "select id from public.payouts where status = 'approved'"
        " and updated_at <= now() - make_interval(secs => $1) order by updated_at limit 20",
        float(min_age_seconds),
    )
    return [r["id"] for r in rows]


def payout_split(amount_cents: int, breakdown: dict) -> tuple[int, int]:
    """(base, bonus) cents of one payout. Breakdowns are cumulative per video, so the base
    part is what base was still unpaid when this payout was made, capped at its amount."""
    unpaid_base = int(breakdown.get("base") or 0) - int(breakdown.get("already_committed") or 0)
    base = max(0, min(amount_cents, unpaid_base))
    return base, amount_cents - base


async def dashboard_rows(conn: asyncpg.Connection, brand_id: UUID) -> dict[str, list[dict]]:
    """Flat tables of the brand's money for AG Studio: dollars as numbers, ISO dates."""
    deals = await conn.fetch(
        "select d.id::text, coalesce(br.product_name, 'Deal') as title, d.creator_id::text,"
        " d.status, d.videos, d.price_cents / 100.0 as agreed,"
        " coalesce(f.amount_cents, 0) / 100.0 as funded,"
        " coalesce(f.refunded_cents, 0) / 100.0 as refunded,"
        " d.go_live_by::text, d.created_at::date::text as created_at"
        " from public.deals d join public.batches b on b.id = d.batch_id"
        " join public.briefs br on br.id = b.brief_id"
        " left join public.deal_funding f on f.deal_id = d.id and f.status = 'captured'"
        " where d.brand_id = $1",
        brand_id,
    )
    milestones = await conn.fetch(
        "select m.id::text, m.deal_id::text, m.seq, m.title, m.status,"
        " m.amount_cents / 100.0 as agreed,"
        " (select max(s.views) from public.milestone_submissions s"
        "  where s.milestone_id = m.id and s.status = 'verified') as views"
        " from public.deal_milestones m join public.deals d on d.id = m.deal_id"
        " where d.brand_id = $1",
        brand_id,
    )
    payout_rows = await conn.fetch(
        "select p.id::text, m.deal_id::text, p.milestone_id::text, d.creator_id::text,"
        " p.status, p.amount_cents, p.breakdown, p.created_at::date::text as date"
        " from public.payouts p join public.deal_milestones m on m.id = p.milestone_id"
        " join public.deals d on d.id = m.deal_id where d.brand_id = $1",
        brand_id,
    )
    payouts = []
    for r in payout_rows:
        breakdown = r["breakdown"]
        if isinstance(breakdown, str):
            breakdown = json.loads(breakdown)
        base, bonus = payout_split(r["amount_cents"], breakdown or {})
        paid = r["status"] == "success"
        payouts.append(
            {
                "id": r["id"],
                "deal_id": r["deal_id"],
                "milestone_id": r["milestone_id"],
                "creator_id": r["creator_id"],
                "status": r["status"],
                "amount": r["amount_cents"] / 100,
                "base": base / 100,
                "bonus": bonus / 100,
                "paid_base": base / 100 if paid else 0.0,
                "paid_bonus": bonus / 100 if paid else 0.0,
                "date": r["date"],
            }
        )
    events = await conn.fetch(
        "select e.id::text, e.deal_id::text, e.kind, e.amount_cents / 100.0 as amount,"
        " e.created_at::date::text as date, e.paypal_ref"
        " from public.money_events e join public.deals d on d.id = e.deal_id"
        " where d.brand_id = $1",
        brand_id,
    )
    creators = await conn.fetch(
        "select distinct c.id::text, c.name, c.handle from public.creators c"
        " join public.deals d on d.creator_id = c.id where d.brand_id = $1",
        brand_id,
    )

    def rows(records):
        return [
            {k: (float(v) if hasattr(v, "is_finite") else v) for k, v in dict(r).items()}
            for r in records
        ]

    return {
        "deals": rows(deals),
        "milestones": rows(milestones),
        "payouts": payouts,
        "money_events": rows(events),
        "creators": rows(creators),
    }

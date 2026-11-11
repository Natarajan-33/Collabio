"""Regression tests for the post-Task-13 review: transient PayPal errors, runs that end
without paying, caps before saving, seeded payouts, early 'paid', and demo reset access."""

import pytest

from app.adapters.paypal import PayPalError
from app.config import get_settings
from app.modules.money import runner
from app.modules.money.service import MoneyService
from tests.fakes import claude_text, claude_tool_use

pytestmark = pytest.mark.db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def verdict(views=400_000):
    return claude_tool_use(
        "record_verification",
        {
            "brief_ok": True,
            "missing_points": [],
            "disclosure_ok": True,
            "views": views,
            "view_confidence": "high",
            "summary": "ok",
        },
        "t1",
    )


async def submit(client, milestone_id):
    return await client.post(
        f"/api/v1/milestones/{milestone_id}/submissions",
        data={"post_url": "https://example.com/p", "caption": "#ad", "claimed_views": "400000"},
        files={"screenshot": ("s.png", PNG, "image/png")},
    )


async def money(client, deal_id):
    return (await client.get(f"/api/v1/deals/{deal_id}/money")).json()


@pytest.fixture(autouse=True)
async def high_limit(brand_client):
    await brand_client.put("/api/v1/me/brand/auto-approve-limit", json={"cents": 1_000_000})
    yield
    await brand_client.put("/api/v1/me/brand/auto-approve-limit", json={"cents": 30_000})


async def test_transient_payout_error_keeps_approved_and_resends(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage, api_db
):
    deal_id, milestones = funded
    fake_paypal.payout_error = PayPalError("PAYPAL_UNREACHABLE", "timeout", http_status=0)
    fake_claude.script += [
        verdict(),
        claude_tool_use("pay_creator", {"reason": "ok"}, "t2"),
        claude_text("done"),
    ]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    view = await money(brand_client, deal_id)
    payout = view["milestones"][0]["payouts"][0]
    assert payout["status"] == "approved"  # not failed: PayPal may have taken it
    assert view["milestones"][0]["committed_cents"] == 40_000

    service = MoneyService(api_db, fake_paypal, None, get_settings(), fake_storage)
    assert await service.resend_approved_payouts(min_age_seconds=0) == 1
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["payouts"][0]["status"] == "sent"
    assert len(fake_paypal.payouts) == 1


async def test_definite_4xx_payout_error_marks_failed(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    fake_paypal.payout_error = PayPalError("RECEIVER_UNREGISTERED", "no", http_status=422)
    fake_claude.script += [
        verdict(),
        claude_tool_use("pay_creator", {"reason": "ok"}, "t2"),
        claude_text("done"),
    ]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["payouts"][0]["status"] == "failed"


async def test_run_that_ends_without_paying_leaves_milestone_verified(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    fake_claude.script += [verdict(), claude_text("Verified; not paying yet.")]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    view = await money(creator_client, deal_id)
    assert view["milestones"][0]["status"] == "verified"


async def test_max_tokens_stop_is_an_error(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    cut = claude_tool_use("pay_creator", {"reason": "o"}, "t2")
    cut["stop_reason"] = "max_tokens"
    fake_claude.script += [cut]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    view = await money(creator_client, deal_id)
    assert view["milestones"][0]["submissions"][0]["run_status"] == "error"
    assert fake_paypal.payouts == []


async def test_cap_is_checked_before_the_proof_is_saved(
    creator_client, funded, fake_storage, api_db, app
):
    deal_id, milestones = funded
    settings = get_settings().model_copy(update={"hackathon_mode": True})
    from app.config import get_settings as dep

    app.dependency_overrides[dep] = lambda: settings
    async with api_db.acquire() as conn:
        user_id = await conn.fetchval(
            "select id from auth.users where email = $1", get_settings().demo_helper_email
        )
        await conn.execute(
            "insert into public.usage_counters (user_id, day, kind, count) values"
            " ($1, current_date, 'settlement', 30) on conflict (user_id, day, kind)"
            " do update set count = 30",
            user_id,
        )
    r = await submit(creator_client, milestones[0])
    assert r.status_code == 429
    view = await money(creator_client, deal_id)
    assert view["milestones"][0]["status"] == "funded"
    assert view["milestones"][0]["submissions"] == []


async def test_seeded_deal_payouts_are_simulated(api_db, fake_paypal, fake_storage):
    from scripts.seed_money import seed_money

    async with api_db.acquire() as conn:
        ids = await seed_money(conn)
        payout_id = await conn.fetchval(
            "select p.id from public.payouts p join public.deal_milestones m"
            " on m.id = p.milestone_id where m.deal_id = $1 and p.status = 'awaiting_approval'",
            ids["Studio Monitors"],
        )
        brand_id = await conn.fetchval(
            "select brand_id from public.deals where id = $1", ids["Studio Monitors"]
        )
    service = MoneyService(api_db, fake_paypal, None, get_settings(), fake_storage)
    view = await service.approve_payout(payout_id, brand_id)
    assert fake_paypal.payouts == []
    m2 = view["milestones"][1]
    assert m2["payouts"][0]["status"] == "success"
    assert m2["status"] == "paid"


async def test_sync_does_not_mark_paid_while_more_is_pending(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage, api_db
):
    deal_id, milestones = funded
    fake_claude.script += [
        verdict(),
        claude_tool_use("pay_creator", {"reason": "ok"}, "t2"),
        claude_text("done"),
    ]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    async with api_db.acquire() as conn:  # a newer payout for the same video is waiting
        await conn.execute(
            "insert into public.payouts (milestone_id, amount_cents, status, sender_batch_id)"
            " values ($1, 500, 'awaiting_approval', 'collabio-extra-' || gen_random_uuid())",
            milestones[0],
        )
    service = MoneyService(api_db, fake_paypal, None, get_settings(), fake_storage)
    await service.sync_sent_payouts()
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["status"] == "verified"


async def test_reset_is_for_demo_personas_only(new_brand_client, app):
    settings = get_settings().model_copy(update={"hackathon_mode": True})
    app.dependency_overrides[get_settings] = lambda: settings
    r = await new_brand_client.post("/api/v1/demo/reset")
    assert r.status_code == 403

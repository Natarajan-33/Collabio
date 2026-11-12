"""Final-review fixes on the payout send path (#1) and funding recovery (#2)."""

import asyncio

import pytest

from app.adapters.paypal import PayPalError
from app.config import get_settings
from app.modules.money import runner
from app.modules.money.service import MoneyService
from tests.api.test_money_review_fixes import (  # noqa: F401 (high_limit is an autouse fixture)
    PNG,
    high_limit,
    money,
    submit,
    verdict,
)
from tests.fakes import claude_text, claude_tool_use

pytestmark = pytest.mark.db


async def _approved_after_timeout(creator_client, brand_client, funded, fake_claude, fake_paypal):
    """Auto-pay whose PayPal call timed out: the payout stays `approved` (outcome unknown)."""
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
    assert payout["status"] == "approved"
    return deal_id, payout["id"]


async def test_4xx_after_an_unknown_outcome_keeps_the_payout_approved(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage, api_db
):
    deal_id, _ = await _approved_after_timeout(
        creator_client, brand_client, funded, fake_claude, fake_paypal
    )
    fake_paypal.payout_error = PayPalError("DUPLICATE_REQUEST", "dup", http_status=422)
    service = MoneyService(api_db, fake_paypal, None, get_settings(), fake_storage)
    await service.resend_approved_payouts(min_age_seconds=0)
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["payouts"][0]["status"] == "approved"  # never "failed"
    assert view["milestones"][0]["committed_cents"] == 40_000
    assert "payout_failed" not in [e["kind"] for e in view["ledger"]]


async def test_4xx_flagged_after_unknown_by_the_adapter_keeps_approved(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    error = PayPalError("DUPLICATE_REQUEST", "dup", http_status=422)
    error.after_unknown = True
    fake_paypal.payout_error = error
    fake_claude.script += [
        verdict(),
        claude_tool_use("pay_creator", {"reason": "ok"}, "t2"),
        claude_text("done"),
    ]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["payouts"][0]["status"] == "approved"


async def test_overlapping_sends_reach_paypal_once(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage, api_db
):
    _, payout_id = await _approved_after_timeout(
        creator_client, brand_client, funded, fake_claude, fake_paypal
    )
    real = fake_paypal.create_payout

    async def slow(*args):
        await asyncio.sleep(1.0)
        return await real(*args)

    fake_paypal.create_payout = slow
    service = MoneyService(api_db, fake_paypal, None, get_settings(), fake_storage)
    from uuid import UUID

    results = await asyncio.gather(
        service.send_payout(UUID(payout_id)), service.send_payout(UUID(payout_id))
    )
    assert sorted(results) == ["approved", "sent"]  # the second found it claimed
    assert len(fake_paypal.payouts) == 1


async def test_fund_again_after_a_lost_capture_recovers_the_first_order(
    brand_client, booked, fake_paypal
):
    """#2: PayPal captured but our capture call failed; "Fund" again must not orphan it."""
    _, deal_id = booked
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    first = r.json()["order_id"]
    fake_paypal.orders[first]["status"] = "COMPLETED"  # captured at PayPal, not recorded here
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    assert r.status_code == 200, r.text
    assert r.json() == {"order_id": first, "approve_url": None}
    view = (await brand_client.get(f"/api/v1/deals/{deal_id}/money")).json()
    assert view["funding"]["status"] == "captured"
    assert len(fake_paypal.orders) == 1  # no second order was created


async def test_fund_again_after_approval_captures_the_approved_order(
    brand_client, booked, fake_paypal
):
    _, deal_id = booked
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    first = r.json()["order_id"]
    fake_paypal.orders[first]["status"] = "APPROVED"  # buyer approved; return page never ran
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")
    assert r.json() == {"order_id": first, "approve_url": None}
    assert fake_paypal.captures == 1


async def test_fund_again_before_approval_creates_a_new_order(brand_client, booked, fake_paypal):
    _, deal_id = booked
    first = (await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")).json()
    second = (await brand_client.post(f"/api/v1/deals/{deal_id}/funding/order")).json()
    assert second["order_id"] != first["order_id"]
    assert second["approve_url"]


async def _counter(api_db, user_id, kind):
    async with api_db.acquire() as conn:
        return await conn.fetchval(
            "select count from public.usage_counters where user_id = $1 and kind = $2"
            " and day = current_date",
            user_id,
            kind,
        )


async def _hackathon(app):
    from app.config import get_settings as dep

    settings = get_settings().model_copy(update={"hackathon_mode": True})
    app.dependency_overrides[dep] = lambda: settings


async def test_junk_upload_does_not_spend_the_settlement_cap(
    creator_client, funded, fake_storage, api_db, app
):
    """#6: the cap is charged after the image is validated (still before anything is saved)."""
    _, milestones = funded
    await _hackathon(app)
    async with api_db.acquire() as conn:
        user_id = await conn.fetchval(
            "select id from auth.users where email = $1", get_settings().demo_helper_email
        )
        await conn.execute("delete from public.usage_counters where user_id = $1", user_id)
    r = await creator_client.post(
        f"/api/v1/milestones/{milestones[0]}/submissions",
        data={"post_url": "https://example.com/p", "claimed_views": "1000"},
        files={"screenshot": ("x.png", b"not an image", "image/png")},
    )
    assert r.status_code == 422
    assert await _counter(api_db, user_id, "settlement") is None


async def test_per_visitor_cap_blocks_one_ip_not_the_persona(
    creator_client, funded, fake_storage, fake_claude, fake_paypal, api_db, app
):
    from app.core.caps import cap_for
    from app.modules.money.usage import ip_key

    _, milestones = funded
    await _hackathon(app)
    noisy = "198.51.100.7"
    async with api_db.acquire() as conn:
        await conn.execute(
            "insert into public.usage_counters (user_id, day, kind, count) values"
            " ($1, current_date, 'settlement', $2) on conflict (user_id, day, kind)"
            " do update set count = excluded.count",
            ip_key(noisy),
            cap_for("settlement_ip"),
        )
    try:
        r = await creator_client.post(
            f"/api/v1/milestones/{milestones[0]}/submissions",
            data={"post_url": "https://example.com/p", "claimed_views": "400000"},
            files={"screenshot": ("shot.png", PNG, "image/png")},
            headers={"x-forwarded-for": noisy},
        )
        assert r.status_code == 429
        fake_claude.script += [claude_text("No verdict.")]
        r = await creator_client.post(
            f"/api/v1/milestones/{milestones[0]}/submissions",
            data={"post_url": "https://example.com/p", "claimed_views": "400000"},
            files={"screenshot": ("shot.png", PNG, "image/png")},
            headers={"x-forwarded-for": "198.51.100.8"},
        )
        assert r.status_code == 200, r.text
        await runner.wait_all()
    finally:
        async with api_db.acquire() as conn:
            await conn.execute("delete from public.usage_counters where kind like 'settlement%'")

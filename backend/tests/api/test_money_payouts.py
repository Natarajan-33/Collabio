"""Brand approvals, payout status from PayPal, closing a deal with a refund, the webhook
and the nightly job."""

import pytest

from app.adapters.paypal import PayPalError
from app.config import get_settings
from app.modules.money import runner
from app.modules.money.service import MoneyService
from tests.fakes import claude_text, claude_tool_use

pytestmark = pytest.mark.db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


async def set_limit(client, cents):
    assert (
        await client.put("/api/v1/me/brand/auto-approve-limit", json={"cents": cents})
    ).status_code == 200


@pytest.fixture(autouse=True)
async def reset_limit(brand_client):
    yield
    await set_limit(brand_client, 30_000)


async def settle(creator_client, fake_claude, milestone_id, views=400_000):
    fake_claude.script += [
        claude_tool_use(
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
        ),
        claude_tool_use("pay_creator", {"reason": "ok"}, "t2"),
        claude_text("done"),
    ]
    r = await creator_client.post(
        f"/api/v1/milestones/{milestone_id}/submissions",
        data={"post_url": "https://example.com/p", "caption": "#ad", "claimed_views": str(views)},
        files={"screenshot": ("s.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    await runner.wait_all()


async def money(client, deal_id):
    return (await client.get(f"/api/v1/deals/{deal_id}/money")).json()


async def queued_payout(brand_client, creator_client, fake_claude, funded):
    """A payout waiting for approval (40,000 > the 30,000 default limit)."""
    deal_id, milestones = funded
    await settle(creator_client, fake_claude, milestones[0])
    view = await money(brand_client, deal_id)
    payout = view["milestones"][0]["payouts"][0]
    assert payout["status"] == "awaiting_approval"
    return deal_id, milestones, payout["id"]


async def test_approve_sends_and_marks_sent(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, _, payout_id = await queued_payout(brand_client, creator_client, fake_claude, funded)
    r = await brand_client.post(f"/api/v1/payouts/{payout_id}/approve")
    assert r.status_code == 200, r.text
    assert [p["amount_cents"] for p in fake_paypal.payouts] == [40_000]
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["payouts"][0]["status"] == "sent"
    # A second approve is refused: the payout already left.
    assert (await brand_client.post(f"/api/v1/payouts/{payout_id}/approve")).status_code == 409


async def test_creator_cannot_approve(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    _, _, payout_id = await queued_payout(brand_client, creator_client, fake_claude, funded)
    assert (await creator_client.post(f"/api/v1/payouts/{payout_id}/approve")).status_code == 403


async def test_reject_sets_needs_changes(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, _, payout_id = await queued_payout(brand_client, creator_client, fake_claude, funded)
    r = await brand_client.post(
        f"/api/v1/payouts/{payout_id}/reject", json={"reason": "Wrong product shown"}
    )
    assert r.status_code == 200, r.text
    view = await money(creator_client, deal_id)
    m = view["milestones"][0]
    assert m["payouts"][0]["status"] == "rejected"
    assert m["payouts"][0]["reject_reason"] == "Wrong product shown"
    assert m["submissions"][0]["status"] == "needs_changes"
    assert m["status"] == "needs_changes"
    assert m["committed_cents"] == 0
    assert fake_paypal.payouts == []


async def test_paypal_error_on_send_marks_failed_and_restores_available(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, _, payout_id = await queued_payout(brand_client, creator_client, fake_claude, funded)
    before = (await money(brand_client, deal_id))["available_cents"]
    fake_paypal.payout_error = PayPalError(
        "INSUFFICIENT_FUNDS", "no money", http_status=422, debug_id="abc"
    )
    r = await brand_client.post(f"/api/v1/payouts/{payout_id}/approve")
    assert r.status_code == 200, r.text
    view = await money(brand_client, deal_id)
    payout = view["milestones"][0]["payouts"][0]
    assert payout["status"] == "failed"
    failed = [e for e in view["ledger"] if e["kind"] == "payout_failed"]
    assert failed and failed[0]["payload"]["debug_id"] == "abc"
    assert view["available_cents"] == before + 40_000


async def test_sync_success_marks_milestone_paid(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage, api_db
):
    deal_id, milestones = funded
    await set_limit(brand_client, 1_000_000)
    await settle(creator_client, fake_claude, milestones[0])
    service = MoneyService(api_db, fake_paypal, None, get_settings(), fake_storage)
    assert await service.sync_sent_payouts() >= 1
    view = await money(brand_client, deal_id)
    m = view["milestones"][0]
    assert m["status"] == "paid"
    assert m["payouts"][0]["status"] == "success"
    assert "payout_succeeded" in [e["kind"] for e in view["ledger"]]


async def test_close_refunds_unspent_excluding_committed(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage, api_db
):
    deal_id, milestones = funded
    await set_limit(brand_client, 1_000_000)
    await settle(creator_client, fake_claude, milestones[0])  # 40,000 sent, not yet success
    async with api_db.acquire() as conn:  # past go_live_by + 7 so the deal may close
        await conn.execute(
            "update public.deal_milestones set status = 'paid' where deal_id = $1", deal_id
        )
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/close")
    assert r.status_code == 200, r.text
    assert fake_paypal.refunds == [
        {"capture_id": fake_paypal.refunds[0]["capture_id"], "amount_cents": 80_000}
    ]
    view = r.json()
    assert view["deal_status"] == "completed"
    assert view["funding"]["refunded_cents"] == 80_000
    assert view["ledger"][-1]["kind"] == "refunded"


async def test_close_before_done_is_409(brand_client, funded, fake_paypal):
    deal_id, _ = funded
    r = await brand_client.post(f"/api/v1/deals/{deal_id}/close")
    assert r.status_code == 409
    assert r.json()["detail"] == "not_closable"


async def test_payout_after_close_409(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage, api_db
):
    deal_id, _, payout_id = await queued_payout(brand_client, creator_client, fake_claude, funded)
    async with api_db.acquire() as conn:
        await conn.execute(
            "update public.deal_milestones set status = 'paid' where deal_id = $1", deal_id
        )
    assert (await brand_client.post(f"/api/v1/deals/{deal_id}/close")).status_code == 200
    r = await brand_client.post(f"/api/v1/payouts/{payout_id}/approve")
    assert r.status_code == 409
    assert r.json()["detail"] == "deal_closed"


async def test_nightly_requires_secret(client, m2_settings):
    r = await client.post("/api/v1/internal/nightly")
    assert r.status_code in (401, 403)


async def test_webhook_without_id_is_accepted_and_ignored(client):
    r = await client.post("/api/v1/webhooks/paypal", json={"event_type": "PING"})
    assert r.status_code == 202

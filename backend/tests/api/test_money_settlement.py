"""Proof submission and the Claude settlement agent paying through PayPal Payouts.

Claude is scripted (FakeClaude) and PayPal is in memory; amounts must always come from
the engine and the brand's limit, never from the model.
"""

import asyncio

import pytest

from app.adapters.paypal import PayPalError
from app.modules.money import runner
from tests.fakes import claude_text, claude_tool_use

pytestmark = pytest.mark.db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


async def set_limit(client, cents):
    r = await client.put("/api/v1/me/brand/auto-approve-limit", json={"cents": cents})
    assert r.status_code == 200, r.text


async def submit(client, milestone_id, *, claimed=400_000, data=PNG, name="shot.png"):
    return await client.post(
        f"/api/v1/milestones/{milestone_id}/submissions",
        data={
            "post_url": "https://example.com/p/1",
            "caption": "Loving my pods #ad",
            "claimed_views": str(claimed),
        },
        files={"screenshot": (name, data, "image/png")},
    )


def verdict(views=400_000, confidence="high", brief_ok=True, disclosure_ok=True):
    return claude_tool_use(
        "record_verification",
        {
            "brief_ok": brief_ok,
            "missing_points": [],
            "disclosure_ok": disclosure_ok,
            "views": views,
            "view_confidence": confidence,
            "summary": "On brief, #ad present.",
        },
        "t1",
    )


def pay(extra=None):
    return claude_tool_use("pay_creator", {"reason": "Verified", **(extra or {})}, "t2")


async def money(client, deal_id):
    return (await client.get(f"/api/v1/deals/{deal_id}/money")).json()


@pytest.fixture(autouse=True)
async def reset_limit(brand_client):
    yield
    await set_limit(brand_client, 30_000)


async def test_happy_path_auto_pays_under_limit(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    await set_limit(brand_client, 100_000)
    fake_claude.script += [verdict(), pay(), claude_text("Paid Priya for Video 1.")]
    r = await submit(creator_client, milestones[0])
    assert r.status_code == 200, r.text
    await runner.wait_all()

    assert len(fake_paypal.payouts) == 1
    assert fake_paypal.payouts[0]["receiver_email"] == "priya-sandbox@example.com"
    assert fake_paypal.payouts[0]["amount_cents"] == 40_000  # base only: no bonus terms
    view = await money(brand_client, deal_id)
    m = view["milestones"][0]
    assert m["status"] == "verified"
    assert m["payouts"][0]["status"] == "sent"
    assert m["submissions"][0]["views"] == 400_000
    kinds = [e["kind"] for e in view["ledger"]]
    assert kinds == ["funded", "payout_queued", "payout_sent"]
    # The first request carried the screenshot as an image block.
    first = fake_claude.requests[0]
    assert first["model"] == "claude-sonnet-5-5"
    assert any(b.get("type") == "image" for b in first["messages"][0]["content"])
    assert first["tool_choice"] == {"type": "auto"}


async def test_same_case_with_limit_30000_goes_to_approval(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    fake_claude.script += [verdict(), pay(), claude_text("Queued for approval.")]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    assert fake_paypal.payouts == []
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["payouts"][0]["status"] == "awaiting_approval"


async def test_model_amount_is_ignored(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    _, milestones = funded
    await set_limit(brand_client, 1_000_000)
    fake_claude.script += [verdict(), pay({"amount_cents": 999_999}), claude_text("Done.")]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    assert [p["amount_cents"] for p in fake_paypal.payouts] == [40_000]


async def test_low_confidence_goes_to_approval(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    await set_limit(brand_client, 1_000_000)
    fake_claude.script += [verdict(confidence="low"), pay(), claude_text("Unsure.")]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    assert fake_paypal.payouts == []
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["payouts"][0]["status"] == "awaiting_approval"


async def test_request_changes_sets_needs_changes_no_money(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    fake_claude.script += [
        claude_tool_use("request_changes", {"message": "Please add #ad."}, "t9"),
        claude_text("Asked for changes."),
    ]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    view = await money(creator_client, deal_id)
    m = view["milestones"][0]
    assert m["status"] == "needs_changes"
    assert m["submissions"][0]["status"] == "needs_changes"
    assert m["submissions"][0]["agent_summary"] == "Please add #ad."
    assert m["payouts"] == []
    assert fake_paypal.payouts == []


async def test_concurrent_settles_same_milestone_single_payout(
    brand_client, creator_client, funded, fake_paypal, fake_storage, api_db
):
    """Two verified submissions paid at once: total committed equals what is owed."""
    from app.config import get_settings
    from app.modules.money.service import MoneyService

    deal_id, milestones = funded
    await set_limit(brand_client, 1_000_000)
    async with api_db.acquire() as conn:
        ids = []
        for _ in range(2):
            ids.append(
                await conn.fetchval(
                    "insert into public.milestone_submissions (milestone_id, post_url,"
                    " claimed_views, screenshot_path, status, brief_ok, disclosure_ok, views,"
                    " view_confidence) values ($1, 'u', 400000, 'p', 'verified', true, true,"
                    " 400000, 'high') returning id",
                    milestones[0],
                )
            )
    service = MoneyService(api_db, fake_paypal, None, get_settings(), fake_storage)
    await asyncio.gather(service.pay_milestone(ids[0], "a"), service.pay_milestone(ids[1], "b"))
    view = await money(brand_client, deal_id)
    assert view["milestones"][0]["committed_cents"] == 40_000
    assert sum(p["amount_cents"] for p in fake_paypal.payouts) == 40_000


async def test_bad_screenshot_422(creator_client, funded, fake_storage):
    _, milestones = funded
    r = await submit(creator_client, milestones[0], data=b"just text", name="shot.png")
    assert r.status_code == 422
    assert r.json()["detail"] == "bad_screenshot"
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)
    r = await submit(creator_client, milestones[0], data=big)
    assert r.status_code == 422


async def test_submit_on_unfunded_deal_409(creator_client, booked, fake_storage, api_db):
    _, deal_id = booked
    async with api_db.acquire() as conn:
        milestone_id = await conn.fetchval(
            "select id from public.deal_milestones where deal_id = $1 order by seq limit 1",
            deal_id,
        )
    r = await submit(creator_client, milestone_id)
    assert r.status_code == 409
    assert r.json()["detail"] == "not_submittable"


async def test_brand_cannot_submit_proof(brand_client, funded, fake_storage):
    _, milestones = funded
    assert (await submit(brand_client, milestones[0])).status_code == 403


async def test_model_error_leaves_retryable(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    fake_claude.script += [RuntimeError("model down")]
    r = await submit(creator_client, milestones[0])
    sub_id = r.json()["submission_id"]
    await runner.wait_all()
    view = await money(creator_client, deal_id)
    sub = view["milestones"][0]["submissions"][0]
    assert sub["status"] == "submitted"
    assert sub["run_status"] == "error"

    await set_limit(brand_client, 1_000_000)
    fake_claude.script += [verdict(), pay(), claude_text("Paid.")]
    r = await creator_client.post(f"/api/v1/submissions/{sub_id}/retry")
    assert r.status_code == 200, r.text
    await runner.wait_all()
    assert len(fake_paypal.payouts) == 1


async def test_paypal_error_on_auto_pay_marks_failed(
    brand_client, creator_client, funded, fake_claude, fake_paypal, fake_storage
):
    deal_id, milestones = funded
    await set_limit(brand_client, 1_000_000)
    fake_paypal.payout_error = PayPalError(
        "INSUFFICIENT_FUNDS", "no money", http_status=422, debug_id="abc"
    )
    fake_claude.script += [verdict(), pay(), claude_text("Tried.")]
    await submit(creator_client, milestones[0])
    await runner.wait_all()
    view = await money(brand_client, deal_id)
    payout = view["milestones"][0]["payouts"][0]
    assert payout["status"] == "failed"
    assert payout["last_error"]["debug_id"] == "abc"
    assert view["available_cents"] == 120_000
    assert "payout_failed" in [e["kind"] for e in view["ledger"]]

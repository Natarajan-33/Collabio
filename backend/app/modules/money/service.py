"""M4 money orchestration: bonus terms, funding, settlement, payouts and refunds.

Amounts always come from `app.core.settlement`; auto-pay is decided only by
`app.core.payout_policy`. PayPal and Claude are injected ports.
"""

import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.adapters.claude import ClaudePort
from app.adapters.db import Database
from app.adapters.paypal import PayPalError, PayPalPort
from app.agents.settlement_agent import run_agent
from app.agents.terms_parser import parse_bonus_terms
from app.config import Settings
from app.core import settlement as engine
from app.core.payout_policy import decide
from app.core.settlement import BonusTerms
from app.modules.money import repo

EXAMPLE_VIEWS = (100_000, 500_000, 1_000_000)


class NotFound(Exception):
    """No such deal for this party (never reveals existence)."""


class AlreadyFunded(Exception):
    """Bonus terms are frozen once the deal is funded."""


class TermsInvalid(Exception):
    def __init__(self, codes: list[str]) -> None:
        super().__init__(", ".join(codes))
        self.codes = codes


class TermsQuestion(Exception):
    def __init__(self, question: str) -> None:
        super().__init__(question)
        self.question = question


class FundingTooLarge(Exception):
    """The funding total would exceed the demo cap."""


class FundingMismatch(Exception):
    """PayPal captured something other than this deal's order and amount."""


class FundingOutdated(Exception):
    """The deal's budget changed after this order was made; start a new checkout."""


def terms_dict(t: BonusTerms) -> dict[str, Any]:
    return engine.terms_to_json(t)


class MoneyService:
    def __init__(
        self,
        db: Database,
        paypal: PayPalPort | None,
        claude: ClaudePort | None,
        settings: Settings,
        storage: Any = None,
    ) -> None:
        self._db = db
        self._paypal = paypal
        self._claude = claude
        self._settings = settings
        self._storage = storage

    # ---- bonus terms -------------------------------------------------------------------

    async def _unfunded_brand_deal(self, conn, deal_id: UUID, brand_id: UUID) -> dict:
        deal = await repo.brand_deal(conn, deal_id, brand_id)
        if deal is None:
            raise NotFound
        if deal["status"] != "booked":
            raise AlreadyFunded
        return deal

    async def preview_bonus(self, deal_id: UUID, brand_id: UUID, text: str) -> dict[str, Any]:
        async with self._db.acquire() as conn:
            deal = await self._unfunded_brand_deal(conn, deal_id, brand_id)
            amounts = [m["amount_cents"] for m in await repo.milestones(conn, deal_id)]
        assert self._claude is not None
        parsed = await parse_bonus_terms(self._claude, self._settings.claude_parser_model, text)
        if isinstance(parsed, str):
            raise TermsQuestion(parsed)
        return self._preview(parsed, amounts, deal["videos"])

    def _preview(self, terms: BonusTerms, amounts: list[int], videos: int) -> dict[str, Any]:
        try:
            total = engine.funding_total(amounts, videos, terms)
        except ValueError as exc:
            raise FundingTooLarge from exc
        return {
            "terms": terms_dict(terms),
            "examples": [
                {"views": v, "bonus_cents": engine.bonus_for(v, terms)} for v in EXAMPLE_VIEWS
            ],
            "max_bonus_per_video_cents": engine.max_bonus_per_video(terms),
            "funding_total_cents": total,
        }

    async def save_bonus(
        self, deal_id: UUID, brand_id: UUID, source_text: str, terms_json: dict[str, Any]
    ) -> dict[str, Any]:
        terms = engine.terms_from_json(terms_json)
        codes = engine.validate_terms(terms)
        if codes:
            raise TermsInvalid(codes)
        async with self._db.acquire() as conn, conn.transaction():
            deal = await self._unfunded_brand_deal(conn, deal_id, brand_id)
            amounts = [m["amount_cents"] for m in await repo.milestones(conn, deal_id)]
            preview = self._preview(terms, amounts, deal["videos"])
            await repo.upsert_bonus_terms(
                conn, deal_id, source_text, terms_dict(terms), preview["max_bonus_per_video_cents"]
            )
        return preview

    async def set_limit(self, brand_id: UUID, cents: int) -> int:
        async with self._db.acquire() as conn:
            await repo.set_auto_approve_limit(conn, brand_id, cents)
        return cents

    # ---- funding -----------------------------------------------------------------------

    async def _funding_total(self, conn, deal: dict) -> int:
        amounts = [m["amount_cents"] for m in await repo.milestones(conn, deal["id"])]
        bonus = await repo.bonus_terms(conn, deal["id"])
        terms = engine.terms_from_json(bonus["terms"]) if bonus else None
        try:
            return engine.funding_total(amounts, deal["videos"], terms)
        except ValueError as exc:
            raise FundingTooLarge from exc

    async def create_order(self, deal_id: UUID, brand_id: UUID) -> dict[str, Any]:
        assert self._paypal is not None
        async with self._db.acquire() as conn:
            deal = await self._unfunded_brand_deal(conn, deal_id, brand_id)
            total = await self._funding_total(conn, deal)
        base = self._settings.public_frontend_url.rstrip("/")
        order = await self._paypal.create_order(
            amount_cents=total,
            custom_id=str(deal_id),
            invoice_id=f"collabio-{uuid.uuid4().hex[:20]}",
            description=f"Collabio deal budget ({deal['videos']} videos + performance bonus)",
            return_url=f"{base}/brand/deals/{deal_id}?funding=return",
            cancel_url=f"{base}/brand/deals/{deal_id}?funding=cancel",
        )
        async with self._db.acquire() as conn:
            if not await repo.upsert_created_order(conn, deal_id, order["id"], total):
                raise AlreadyFunded
        return {"order_id": order["id"], "approve_url": order["approve_url"]}

    async def capture(self, deal_id: UUID, brand_id: UUID, order_id: str) -> dict[str, Any]:
        """Capture once: concurrent or repeated calls see the first capture's result."""
        assert self._paypal is not None
        mismatch = False
        async with self._db.acquire() as conn, conn.transaction():
            deal = await repo.brand_deal(conn, deal_id, brand_id)
            if deal is None:
                raise NotFound
            row = await repo.funding(conn, deal_id, lock=True)
            if row is None or row["paypal_order_id"] != order_id:
                raise FundingMismatch
            if row["status"] != "captured":
                if await self._funding_total(conn, deal) != row["amount_cents"]:
                    raise FundingOutdated
                result = await self._paypal.capture_order(order_id)
                if (
                    result["status"] != "COMPLETED"
                    or result.get("capture_status", "COMPLETED") != "COMPLETED"
                    or result["custom_id"] != str(deal_id)
                    or result["amount_cents"] != row["amount_cents"]
                ):
                    await repo.mark_funding_failed(conn, deal_id)
                    mismatch = True
                else:
                    await repo.mark_captured(conn, deal_id, result["capture_id"])
                    await repo.add_event(
                        conn, deal_id, "funded", row["amount_cents"], result["capture_id"]
                    )
        if mismatch:
            raise FundingMismatch
        return await self.money_view(deal_id, brand_id=brand_id, creator_id=None)

    # ---- money view ----------------------------------------------------------------------

    async def money_view(
        self, deal_id: UUID, *, brand_id: UUID | None, creator_id: UUID | None
    ) -> dict[str, Any]:
        async with self._db.acquire() as conn:
            deal = await repo.party_deal(conn, deal_id, brand_id=brand_id, creator_id=creator_id)
            if deal is None:
                raise NotFound
            milestones = await repo.milestones(conn, deal_id)
            bonus = await repo.bonus_terms(conn, deal_id)
            fund = await repo.funding(conn, deal_id)
            subs = await repo.submissions_for_deal(conn, deal_id)
            payouts = await repo.payouts_for_deal(conn, deal_id)
            ledger = await repo.ledger(conn, deal_id)
            limit = await repo.auto_approve_limit(conn, deal["brand_id"]) if brand_id else None
        terms = engine.terms_from_json(bonus["terms"]) if bonus else None
        amounts = [m["amount_cents"] for m in milestones]
        captured = fund["amount_cents"] if fund and fund["status"] == "captured" else 0
        try:
            total = captured or engine.funding_total(amounts, deal["videos"], terms)
        except ValueError:
            total = sum(amounts)
        refunded = fund["refunded_cents"] if fund else 0
        committed_all = sum(p["amount_cents"] for p in payouts if p["status"] in repo.LIVE_PAYOUT)
        out_milestones = []
        for m in milestones:
            m_subs = [s for s in subs if s["milestone_id"] == m["id"]]
            m_pays = [p for p in payouts if p["milestone_id"] == m["id"]]
            state = milestone_state(m, m_subs, m_pays)
            out_milestones.append(
                {
                    "id": str(m["id"]),
                    "seq": m["seq"],
                    "title": m["title"],
                    "amount_cents": m["amount_cents"],
                    "status": m["status"],
                    "owed_cents": engine.owed(state, terms),
                    "committed_cents": state.committed_cents,
                    "submissions": [submission_view(s) for s in m_subs],
                    "payouts": [payout_view(p) for p in m_pays],
                }
            )
        return {
            "deal_id": str(deal_id),
            "deal_status": deal["status"],
            "videos": deal["videos"],
            "funding": None if fund is None else funding_view(fund),
            "bonus_terms": terms_dict(terms) if terms else None,
            "bonus_source_text": bonus["source_text"] if bonus else None,
            "funding_total_cents": total,
            "auto_approve_limit_cents": limit,
            "milestones": out_milestones,
            "ledger": [ledger_view(e) for e in ledger],
            "available_cents": engine.available(captured, committed_all, refunded),
            "can_close": can_close(deal, milestones),
        }

    # ---- proof and settlement -------------------------------------------------------------

    async def submit_proof(
        self,
        milestone_id: UUID,
        creator_id: UUID,
        *,
        post_url: str,
        caption: str,
        claimed_views: int,
        screenshot: bytes,
    ) -> UUID:
        kind = image_kind(screenshot)
        if kind is None or len(screenshot) > MAX_SCREENSHOT_BYTES:
            raise BadScreenshot
        async with self._db.acquire() as conn:
            m = await repo.creator_milestone(conn, milestone_id, creator_id)
            if m is None:
                raise NotFound
            if m["deal_status"] != "funded" or m["status"] not in SUBMITTABLE:
                raise NotSubmittable
        path = f"{m['deal_id']}/{milestone_id}/{uuid.uuid4()}.{kind}"
        await self._storage.upload(path, screenshot, f"image/{'jpeg' if kind == 'jpg' else kind}")
        async with self._db.acquire() as conn, conn.transaction():
            submission_id = await repo.insert_submission(
                conn, milestone_id, post_url, caption, claimed_views, path
            )
            await repo.set_milestone_status(conn, milestone_id, "submitted")
        return submission_id

    async def retry(self, submission_id: UUID, creator_id: UUID) -> None:
        async with self._db.acquire() as conn:
            ctx = await repo.submission_context(conn, submission_id)
        if ctx is None or ctx["creator_id"] != creator_id:
            raise NotFound

    async def settle(self, submission_id: UUID) -> str:
        """One settlement run for a submission; returns the run status."""
        async with self._db.acquire() as conn:
            if not await repo.claim_run(conn, submission_id):
                return "skipped"
            ctx = await repo.submission_context(conn, submission_id)
        assert ctx is not None and self._claude is not None
        try:
            image = await self._storage.download(ctx["screenshot_path"])
            content = settlement_prompt(ctx, image)
            transcript = await run_agent(
                self._claude,
                self._settings.claude_settlement_model,
                content,
                self._handlers(submission_id, ctx),
            )
        except Exception as exc:  # noqa: BLE001 - model down, refusal, storage: retryable
            async with self._db.acquire() as conn:
                await repo.finish_run(conn, submission_id, "error", [], str(exc)[:500])
            return "error"
        async with self._db.acquire() as conn:
            await repo.finish_run(conn, submission_id, "done", transcript)
        return "done"

    def _handlers(self, submission_id: UUID, ctx: dict) -> dict:
        async def get_deal_context(_: dict) -> dict:
            async with self._db.acquire() as conn:
                bonus = await repo.bonus_terms(conn, ctx["deal_id"])
            return {
                "product": ctx["product_name"],
                "product_summary": ctx["product_summary"],
                "brand": ctx["brand_name"],
                "agreed_conditions": list(ctx["conditions"] or []),
                "format": ctx["format"],
                "disclosure_rule": DISCLOSURE_RULE,
                "video": {"title": ctx["title"], "agreed_price_cents": ctx["amount_cents"]},
                "bonus_terms": bonus["terms"] if bonus else None,
                "submission": {
                    "post_url": ctx["post_url"],
                    "caption": ctx["caption"],
                    "views_claimed_by_creator": ctx["claimed_views"],
                },
            }

        async def record_verification(args: dict) -> dict:
            async with self._db.acquire() as conn:
                await repo.record_verification(
                    conn,
                    submission_id,
                    brief_ok=bool(args.get("brief_ok")),
                    disclosure_ok=bool(args.get("disclosure_ok")),
                    missing_points=[str(p) for p in args.get("missing_points") or []][:10],
                    views=int(args.get("views") or 0),
                    view_confidence=args.get("view_confidence")
                    if args.get("view_confidence") in ("high", "medium", "low")
                    else "low",
                    summary=str(args.get("summary") or ""),
                )
            return {"recorded": True}

        async def quote_payout(_: dict) -> dict:
            async with self._db.acquire() as conn:
                return await self._quote(conn, submission_id)

        async def pay_creator(args: dict) -> dict:
            return await self.pay_milestone(submission_id, str(args.get("reason") or ""))

        async def request_changes(args: dict) -> dict:
            async with self._db.acquire() as conn, conn.transaction():
                await repo.request_changes(conn, submission_id, str(args.get("message") or ""))
                await repo.set_milestone_status(conn, ctx["milestone_id"], "needs_changes")
            return {"requested": True}

        return {
            "get_deal_context": get_deal_context,
            "record_verification": record_verification,
            "quote_payout": quote_payout,
            "pay_creator": pay_creator,
            "request_changes": request_changes,
        }

    async def _quote(self, conn, submission_id: UUID) -> dict[str, Any]:
        """The engine's view of what this submission's milestone is owed right now."""
        ctx = await repo.submission_context(conn, submission_id)
        assert ctx is not None
        subs = await repo.milestone_submissions(conn, ctx["milestone_id"])
        pays = await repo.milestone_payouts(conn, ctx["milestone_id"])
        bonus = await repo.bonus_terms(conn, ctx["deal_id"])
        fund = await repo.funding(conn, ctx["deal_id"])
        terms = engine.terms_from_json(bonus["terms"]) if bonus else None
        state = milestone_state({"amount_cents": ctx["amount_cents"]}, subs, pays)
        captured = fund["amount_cents"] if fund and fund["status"] == "captured" else 0
        avail = engine.available(
            captured,
            await repo.deal_committed(conn, ctx["deal_id"]),
            fund["refunded_cents"] if fund else 0,
        )
        sub = next(s for s in subs if s["id"] == submission_id)
        payable = engine.payable(state, terms, avail)
        decision = decide(
            payable,
            ctx["auto_approve_limit_cents"],
            sub["view_confidence"] or "low",
            sub["views"] or 0,
            sub["claimed_views"],
            bool(sub["brief_ok"]),
            bool(sub["disclosure_ok"]),
        )
        return {
            "payable_cents": payable,
            "breakdown": engine.breakdown(state, terms),
            "decision": decision,
            "auto_approve_limit_cents": ctx["auto_approve_limit_cents"],
            "deal_status": ctx["deal_status"],
        }

    async def pay_milestone(self, submission_id: UUID, reason: str) -> dict[str, Any]:
        """Re-quote under a lock on the milestone, then pay (auto) or queue (approval)."""
        async with self._db.acquire() as conn, conn.transaction():
            ctx = await repo.submission_context(conn, submission_id)
            assert ctx is not None
            if ctx["deal_status"] != "funded":
                return {"outcome": "none", "reason": "deal_closed"}
            await repo.lock_milestone(conn, ctx["milestone_id"])
            quote = await self._quote(conn, submission_id)
            decision = quote["decision"]
            if decision == "none":
                return {"outcome": "none", "payable_cents": 0}
            status_ = "approved" if decision == "auto" else "awaiting_approval"
            breakdown = {**quote["breakdown"], "reason": reason[:300]}
            payout_id = await repo.insert_payout(
                conn,
                ctx["milestone_id"],
                submission_id,
                quote["payable_cents"],
                breakdown,
                status_,
            )
            await repo.add_event(
                conn,
                ctx["deal_id"],
                "payout_queued",
                quote["payable_cents"],
                payload={"payout_id": str(payout_id), "decision": decision},
            )
            await repo.set_milestone_status(conn, ctx["milestone_id"], "verified")
        if decision == "auto":
            sent = await self.send_payout(payout_id)
            return {"outcome": sent, "amount_cents": quote["payable_cents"]}
        return {"outcome": "awaiting_approval", "amount_cents": quote["payable_cents"]}

    async def send_payout(self, payout_id: UUID) -> str:
        """Send an approved payout through PayPal Payouts: `sent` or `failed`."""
        assert self._paypal is not None
        async with self._db.acquire() as conn:
            p = await repo.payout(conn, payout_id)
            ctx = await repo.submission_context(conn, p["submission_id"])
        receiver = ctx["payout_email"] or self._settings.paypal_receiver_email
        note = f"Collabio: {ctx['title']} for {ctx['product_name'] or 'your sponsor'}"
        try:
            if not receiver:
                raise PayPalError("NO_PAYOUT_EMAIL", "creator has no PayPal email", http_status=0)
            res = await self._paypal.create_payout(
                p["sender_batch_id"], receiver, p["amount_cents"], note
            )
        except PayPalError as exc:
            error = {"code": exc.code, "message": exc.message, "debug_id": exc.debug_id}
            async with self._db.acquire() as conn, conn.transaction():
                await repo.update_payout(conn, payout_id, status="failed", last_error=error)
                await repo.add_event(
                    conn, ctx["deal_id"], "payout_failed", p["amount_cents"], payload=error
                )
            return "failed"
        async with self._db.acquire() as conn, conn.transaction():
            await repo.update_payout(
                conn,
                payout_id,
                status="sent",
                paypal_batch_id=res["batch_id"],
                paypal_item_id=res["item_id"],
            )
            await repo.add_event(
                conn, ctx["deal_id"], "payout_sent", p["amount_cents"], res["batch_id"]
            )
        return "sent"

    # ---- approvals, status, close ----------------------------------------------------------

    async def _brand_payout(self, conn, payout_id: UUID, brand_id: UUID) -> dict:
        p = await repo.payout_with_deal(conn, payout_id, lock=True)
        if p is None or p["brand_id"] != brand_id:
            raise NotFound
        if p["deal_status"] != "funded":
            raise DealClosed
        if p["status"] != "awaiting_approval":
            raise NotAwaiting
        return p

    async def approve_payout(self, payout_id: UUID, brand_id: UUID) -> dict[str, Any]:
        async with self._db.acquire() as conn, conn.transaction():
            p = await self._brand_payout(conn, payout_id, brand_id)
            await repo.update_payout(conn, payout_id, status="approved", decided_by=brand_id)
        await self.send_payout(payout_id)
        return await self.money_view(p["deal_id"], brand_id=brand_id, creator_id=None)

    async def reject_payout(self, payout_id: UUID, brand_id: UUID, reason: str) -> dict[str, Any]:
        async with self._db.acquire() as conn, conn.transaction():
            p = await self._brand_payout(conn, payout_id, brand_id)
            await repo.update_payout(
                conn, payout_id, status="rejected", reject_reason=reason, decided_by=brand_id
            )
            await repo.add_event(
                conn,
                p["deal_id"],
                "payout_rejected",
                p["amount_cents"],
                payload={"payout_id": str(payout_id), "reason": reason},
            )
            if p["submission_id"] is not None:
                await repo.request_changes(conn, p["submission_id"], reason)
            await repo.set_milestone_status(conn, p["milestone_id"], "needs_changes")
        return await self.money_view(p["deal_id"], brand_id=brand_id, creator_id=None)

    async def sync_payout(self, payout_id: UUID) -> str:
        """Bring one `sent` payout up to date with PayPal; returns its status."""
        assert self._paypal is not None
        async with self._db.acquire() as conn:
            p = await repo.payout_with_deal(conn, payout_id)
        if p is None or p["status"] != "sent" or not p["paypal_batch_id"]:
            return p["status"] if p else "missing"
        batch = await self._paypal.get_payout_batch(p["paypal_batch_id"])
        item = (batch.get("item_status") or "").upper()
        if item == "SUCCESS":
            new, kind = "success", "payout_succeeded"
        elif item in PAYOUT_FAILED:
            new, kind = "failed", "payout_failed"
        else:
            return "sent"
        async with self._db.acquire() as conn, conn.transaction():
            locked = await repo.payout_with_deal(conn, payout_id, lock=True)
            if locked is None or locked["status"] != "sent":
                return locked["status"] if locked else "missing"
            fields: dict[str, Any] = {"status": new, "paypal_item_id": batch.get("item_id")}
            if new == "failed":
                fields["last_error"] = {"code": item, "errors": batch.get("errors")}
            await repo.update_payout(conn, payout_id, **fields)
            await repo.add_event(conn, p["deal_id"], kind, p["amount_cents"], batch.get("item_id"))
            if new == "success":
                await repo.set_milestone_status(conn, p["milestone_id"], "paid")
        return new

    async def sync_sent_payouts(self) -> int:
        async with self._db.acquire() as conn:
            ids = await repo.sent_payout_ids(conn)
        changed = 0
        for payout_id in ids:
            try:
                if await self.sync_payout(payout_id) != "sent":
                    changed += 1
            except PayPalError:
                continue
        return changed

    async def close_deal(self, deal_id: UUID, brand_id: UUID) -> dict[str, Any]:
        """Refund whatever the creator has not earned and complete the deal."""
        assert self._paypal is not None
        async with self._db.acquire() as conn, conn.transaction():
            deal = await repo.brand_deal(conn, deal_id, brand_id)
            if deal is None:
                raise NotFound
            fund = await repo.funding(conn, deal_id, lock=True)
            milestones = await repo.milestones(conn, deal_id)
            if fund is None or fund["status"] != "captured" or not can_close(deal, milestones):
                raise NotClosable
            await repo.reject_awaiting_for_deal(conn, deal_id, "Deal closed before approval")
            refund = engine.refund_due(
                fund["amount_cents"],
                await repo.deal_committed(conn, deal_id),
                fund["refunded_cents"],
            )
            if refund > 0:
                res = await self._paypal.refund_capture(
                    fund["capture_id"],
                    refund,
                    "Unspent Collabio deal budget",
                    request_id=f"refund-{deal_id}-{fund['refunded_cents']}",
                )
                await repo.add_refund(conn, deal_id, refund)
                await repo.add_event(conn, deal_id, "refunded", refund, res["id"])
            await repo.set_deal_status(conn, deal_id, "completed")
        return await self.money_view(deal_id, brand_id=brand_id, creator_id=None)

    async def nightly(self, redispatch) -> dict[str, int]:
        """Sync payouts and retry stuck settlement runs; also keeps the database active."""
        synced = await self.sync_sent_payouts()
        async with self._db.acquire() as conn:
            stale = await repo.stale_error_runs(conn)
        for submission_id in stale:
            redispatch(submission_id)
        return {"payouts_synced": synced, "runs_retried": len(stale)}

    async def handle_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify a PayPal webhook and sync the payout it names. False when unverified."""
        assert self._paypal is not None
        if not self._settings.paypal_webhook_id:
            return False
        if not await self._paypal.verify_webhook(headers, body, self._settings.paypal_webhook_id):
            return False
        event = json.loads(body)
        resource = event.get("resource") or {}
        ref = (
            resource.get("payout_item_id")
            or resource.get("payout_batch_id")
            or (resource.get("payout_item") or {}).get("sender_item_id")
        )
        if ref:
            async with self._db.acquire() as conn:
                payout_id = await repo.payout_by_paypal_ref(conn, ref)
            if payout_id is not None:
                await self.sync_payout(payout_id)
        return True


PAYOUT_FAILED = {"FAILED", "RETURNED", "BLOCKED", "DENIED", "REFUNDED", "REVERSED"}


class DealClosed(Exception):
    """The deal is completed: no more payouts."""


class NotAwaiting(Exception):
    """The payout is not waiting for the brand any more."""


class NotClosable(Exception):
    """The deal is not funded, or still has milestones to deliver."""


DISCLOSURE_RULE = (
    "The post must disclose the sponsorship clearly, e.g. #ad, #sponsored or 'paid partnership'."
)
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
SUBMITTABLE = ("funded", "needs_changes", "verified", "paid", "submitted")


class BadScreenshot(Exception):
    """Not a PNG/JPG, or larger than 5 MB."""


class NotSubmittable(Exception):
    """The deal is not funded, or the milestone cannot take proof now."""


def image_kind(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def settlement_prompt(ctx: dict, image: bytes) -> list[dict[str, Any]]:
    kind = image_kind(image) or "png"
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg" if kind == "jpg" else "image/png",
                "data": base64.b64encode(image).decode(),
            },
        },
        {
            "type": "text",
            "text": (
                f"Settle this submission for {ctx['title']} of the deal for "
                f"{ctx['product_name'] or 'the product'}. The image above is the creator's "
                f"analytics screenshot. Use the tools."
            ),
        },
    ]


def milestone_state(m: dict, subs: list[dict], pays: list[dict]) -> engine.MilestoneState:
    """What the engine needs about one milestone, from its submissions and payouts."""
    verified = [s for s in subs if s["status"] == "verified" and s["views"] is not None]
    return engine.MilestoneState(
        amount_cents=m["amount_cents"],
        verified=bool(verified),
        best_verified_views=max((s["views"] for s in verified), default=0),
        committed_cents=sum(p["amount_cents"] for p in pays if p["status"] in repo.LIVE_PAYOUT),
    )


def can_close(deal: dict, milestones: list[dict], today: date | None = None) -> bool:
    if deal["status"] != "funded":
        return False
    today = today or datetime.now(UTC).date()
    all_paid = all(m["status"] == "paid" for m in milestones)
    return all_paid or today > deal["go_live_by"] + timedelta(days=7)


def funding_view(fund: dict) -> dict[str, Any]:
    return {
        "status": fund["status"],
        "amount_cents": fund["amount_cents"],
        "refunded_cents": fund["refunded_cents"],
        "capture_id": fund["capture_id"],
        "captured_at": fund["captured_at"].isoformat() if fund["captured_at"] else None,
    }


def submission_view(s: dict) -> dict[str, Any]:
    return {
        "id": str(s["id"]),
        "post_url": s["post_url"],
        "caption": s["caption"],
        "claimed_views": s["claimed_views"],
        "status": s["status"],
        "brief_ok": s["brief_ok"],
        "disclosure_ok": s["disclosure_ok"],
        "missing_points": list(s["missing_points"] or []),
        "views": s["views"],
        "view_confidence": s["view_confidence"],
        "agent_summary": s["agent_summary"],
        "screenshot_url": None,
        "run_status": s.get("run_status"),
        "created_at": s["created_at"].isoformat(),
    }


def payout_view(p: dict) -> dict[str, Any]:
    return {
        "id": str(p["id"]),
        "amount_cents": p["amount_cents"],
        "status": p["status"],
        "breakdown": p["breakdown"] or {},
        "paypal_batch_id": p["paypal_batch_id"],
        "paypal_item_id": p["paypal_item_id"],
        "reject_reason": p["reject_reason"],
        "last_error": p["last_error"],
        "created_at": p["created_at"].isoformat(),
    }


def ledger_view(e: dict) -> dict[str, Any]:
    return {
        "id": e["id"],
        "kind": e["kind"],
        "amount_cents": e["amount_cents"],
        "paypal_ref": e["paypal_ref"],
        "payload": e["payload"],
        "created_at": e["created_at"].isoformat(),
    }

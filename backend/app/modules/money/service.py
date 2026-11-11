"""M4 money orchestration: bonus terms, funding, settlement, payouts and refunds.

Amounts always come from `app.core.settlement`; auto-pay is decided only by
`app.core.payout_policy`. PayPal and Claude are injected ports.
"""

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.adapters.claude import ClaudePort
from app.adapters.db import Database
from app.adapters.paypal import PayPalPort
from app.agents.terms_parser import parse_bonus_terms
from app.config import Settings
from app.core import settlement as engine
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
            invoice_id=f"collabio-{deal_id}-{int(time.time())}",
            description=f"Collabio deal budget ({deal['videos']} videos + performance bonus)",
            return_url=f"{base}/brand/deals/{deal_id}?funding=return",
            cancel_url=f"{base}/brand/deals/{deal_id}?funding=cancel",
        )
        async with self._db.acquire() as conn:
            await repo.upsert_created_order(conn, deal_id, order["id"], total)
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
                result = await self._paypal.capture_order(order_id)
                if (
                    result["status"] != "COMPLETED"
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
        try:
            total = engine.funding_total(amounts, deal["videos"], terms)
        except ValueError:
            total = sum(amounts)
        captured = fund["amount_cents"] if fund and fund["status"] == "captured" else 0
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

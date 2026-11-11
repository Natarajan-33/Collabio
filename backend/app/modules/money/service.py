"""M4 money orchestration: bonus terms, funding, settlement, payouts and refunds.

Amounts always come from `app.core.settlement`; auto-pay is decided only by
`app.core.payout_policy`. PayPal and Claude are injected ports.
"""

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

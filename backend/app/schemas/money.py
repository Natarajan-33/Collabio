"""Request and response models for M4 money: bonus terms, funding, proof, payouts."""

from typing import Literal

from pydantic import BaseModel, Field


class CpmIn(BaseModel):
    rate_cents_per_1k: int = Field(ge=1)
    starts_after_views: int = Field(ge=0)
    cap_cents: int = Field(ge=1)


class TierIn(BaseModel):
    views: int = Field(ge=1)
    bonus_cents: int = Field(ge=1)


class BonusTermsIn(BaseModel):
    cpm: CpmIn | None = None
    tiers: list[TierIn] = Field(default_factory=list, max_length=5)


class BonusPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class BonusExample(BaseModel):
    views: int
    bonus_cents: int


class BonusPreview(BaseModel):
    terms: BonusTermsIn
    examples: list[BonusExample]
    max_bonus_per_video_cents: int
    funding_total_cents: int


class BonusTermsPut(BaseModel):
    source_text: str = Field(default="", max_length=2000)
    terms: BonusTermsIn


class AutoApproveLimit(BaseModel):
    cents: int = Field(ge=0, le=1_000_000)


class FundingCapture(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)


class FundingOrder(BaseModel):
    order_id: str
    approve_url: str | None


class FundingView(BaseModel):
    status: Literal["created", "captured", "failed"]
    amount_cents: int
    refunded_cents: int
    capture_id: str | None
    captured_at: str | None


class SubmissionView(BaseModel):
    id: str
    post_url: str
    caption: str
    claimed_views: int
    status: str
    brief_ok: bool | None
    disclosure_ok: bool | None
    missing_points: list[str]
    views: int | None
    view_confidence: str | None
    agent_summary: str | None
    screenshot_url: str | None
    run_status: str | None
    created_at: str


class PayoutView(BaseModel):
    id: str
    amount_cents: int
    status: str
    breakdown: dict
    paypal_batch_id: str | None
    paypal_item_id: str | None
    reject_reason: str | None
    last_error: dict | None
    created_at: str


class MilestoneMoney(BaseModel):
    id: str
    seq: int
    title: str
    amount_cents: int
    status: str
    owed_cents: int
    committed_cents: int
    submissions: list[SubmissionView]
    payouts: list[PayoutView]


class LedgerEntry(BaseModel):
    id: int
    kind: str
    amount_cents: int
    paypal_ref: str | None
    payload: dict
    created_at: str


class MoneyView(BaseModel):
    deal_id: str
    deal_status: str
    videos: int
    funding: FundingView | None
    bonus_terms: BonusTermsIn | None
    bonus_source_text: str | None
    funding_total_cents: int
    auto_approve_limit_cents: int | None
    milestones: list[MilestoneMoney]
    ledger: list[LedgerEntry]
    available_cents: int
    can_close: bool

"""M4 money endpoints: bonus terms, the auto-approve limit, funding, proof and payouts."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.claude import ClaudePort, ClaudeUnavailable
from app.adapters.db import Database
from app.adapters.paypal import PayPalError, PayPalPort
from app.api.deps import (
    CurrentUser,
    get_claude,
    get_db,
    get_paypal,
    onboarded_user,
    require_role,
)
from app.config import Settings, get_settings
from app.modules.briefs import service as briefs_service
from app.modules.money import service, usage
from app.modules.money.service import MoneyService
from app.modules.offers import service as offers_service
from app.schemas.money import (
    AutoApproveLimit,
    BonusPreview,
    BonusPreviewRequest,
    BonusTermsPut,
    FundingCapture,
    FundingOrder,
    MoneyView,
)

router = APIRouter(tags=["money"])

BrandUser = Annotated[CurrentUser, Depends(require_role("brand"))]


@contextmanager
def http_errors() -> Iterator[None]:
    """Maps money service errors onto the HTTP error contract."""
    try:
        yield
    except service.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from exc
    except service.AlreadyFunded as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_funded") from exc
    except service.TermsInvalid as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": "terms_invalid", "errors": exc.codes}
        ) from exc
    except service.TermsQuestion as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "terms_question", "question": exc.question},
        ) from exc
    except service.FundingMismatch as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "funding_mismatch") from exc
    except service.FundingTooLarge as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "funding_too_large") from exc
    except ClaudeUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "claude_unavailable") from exc
    except PayPalError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": exc.code, "message": exc.message, "debug_id": exc.debug_id},
        ) from exc


async def brand_id_of(user: CurrentUser, db: Database) -> UUID:
    brand_id = await briefs_service.find_brand_id(db, user.id)
    if brand_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return brand_id


@router.post("/deals/{deal_id}/bonus-terms/preview")
async def preview_bonus_terms(
    deal_id: UUID,
    req: BonusPreviewRequest,
    user: BrandUser,
    db: Annotated[Database, Depends(get_db)],
    claude: Annotated[ClaudePort, Depends(get_claude)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BonusPreview:
    """Claude reads the plain-English bonus; the engine prices it and the funding total."""
    brand_id = await brand_id_of(user, db)
    await usage.consume(db, user.id, "bonus_preview", settings)
    with http_errors():
        return BonusPreview(
            **await MoneyService(db, None, claude, settings).preview_bonus(
                deal_id, brand_id, req.text
            )
        )


@router.put("/deals/{deal_id}/bonus-terms")
async def put_bonus_terms(
    deal_id: UUID,
    req: BonusTermsPut,
    user: BrandUser,
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BonusPreview:
    """Save the bonus terms (until the deal is funded)."""
    brand_id = await brand_id_of(user, db)
    with http_errors():
        return BonusPreview(
            **await MoneyService(db, None, None, settings).save_bonus(
                deal_id, brand_id, req.source_text, req.terms.model_dump()
            )
        )


@router.put("/me/brand/auto-approve-limit")
async def put_auto_approve_limit(
    req: AutoApproveLimit,
    user: BrandUser,
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AutoApproveLimit:
    """Payouts at or below this amount are sent without asking the brand."""
    brand_id = await brand_id_of(user, db)
    cents = await MoneyService(db, None, None, settings).set_limit(brand_id, req.cents)
    return AutoApproveLimit(cents=cents)


async def party_of(user: CurrentUser, db: Database) -> tuple[UUID | None, UUID | None]:
    """(brand id, creator id) of the signed-in user: exactly one is set."""
    if user.role == "brand":
        return await brand_id_of(user, db), None
    creator_id = await offers_service.find_creator_id(db, user.id)
    if creator_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return None, creator_id


@router.post("/deals/{deal_id}/funding/order")
async def create_funding_order(
    deal_id: UUID,
    user: BrandUser,
    db: Annotated[Database, Depends(get_db)],
    paypal: Annotated[PayPalPort, Depends(get_paypal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FundingOrder:
    """A PayPal order for the deal's full budget: milestones plus the maximum bonus."""
    brand_id = await brand_id_of(user, db)
    with http_errors():
        return FundingOrder(
            **await MoneyService(db, paypal, None, settings).create_order(deal_id, brand_id)
        )


@router.post("/deals/{deal_id}/funding/capture")
async def capture_funding(
    deal_id: UUID,
    req: FundingCapture,
    user: BrandUser,
    db: Annotated[Database, Depends(get_db)],
    paypal: Annotated[PayPalPort, Depends(get_paypal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MoneyView:
    """Capture the approved order; repeated or concurrent calls return the first result."""
    brand_id = await brand_id_of(user, db)
    with http_errors():
        return MoneyView(
            **await MoneyService(db, paypal, None, settings).capture(
                deal_id, brand_id, req.order_id
            )
        )


@router.get("/deals/{deal_id}/money")
async def get_money(
    deal_id: UUID,
    user: Annotated[CurrentUser, Depends(onboarded_user)],
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MoneyView:
    """Funding, milestones with proof and payouts, the ledger and what is still held."""
    brand_id, creator_id = await party_of(user, db)
    with http_errors():
        return MoneyView(
            **await MoneyService(db, None, None, settings).money_view(
                deal_id, brand_id=brand_id, creator_id=creator_id
            )
        )

"""M4 money endpoints: bonus terms, the auto-approve limit, funding, proof and payouts."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.claude import ClaudePort, ClaudeUnavailable
from app.adapters.db import Database
from app.adapters.paypal import PayPalError
from app.api.deps import CurrentUser, get_claude, get_db, require_role
from app.config import Settings, get_settings
from app.modules.briefs import service as briefs_service
from app.modules.money import service, usage
from app.modules.money.service import MoneyService
from app.schemas.money import (
    AutoApproveLimit,
    BonusPreview,
    BonusPreviewRequest,
    BonusTermsPut,
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

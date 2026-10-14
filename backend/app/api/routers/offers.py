from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.api.deps import CurrentUser, get_db, require_role
from app.core.terms import GoLiveInPast
from app.modules.offers import service
from app.modules.offers.service import OffersService
from app.modules.threads.repo import StaleThread
from app.schemas.offers import (
    AcceptRequest,
    CreatorCounterPreview,
    CreatorCounterPreviewRequest,
    CreatorCounterRequest,
    DeclineRequest,
    OfferCounts,
    OfferDesk,
    OfferListItem,
    OfferSort,
    OfferTab,
)

router = APIRouter(tags=["offers"])

OFFER_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "`not_found`"}}
ACTION_ERRORS = OFFER_NOT_FOUND | {
    status.HTTP_409_CONFLICT: {
        "description": "`terms_changed`, `stale_status`, `action_not_allowed`"
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "`below_floor`, `go_live_in_past` (counter only)"
    },
}


async def my_offers(
    user: Annotated[CurrentUser, Depends(require_role("creator"))],
    db: Annotated[Database, Depends(get_db)],
) -> OffersService:
    """The offers of the signed-in creator."""
    creator_id = await service.find_creator_id(db, user.id)
    if creator_id is None:  # a creator profile without its creator row: onboarding never finished
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return OffersService(db, creator_id)


Offers = Annotated[OffersService, Depends(my_offers)]


def _today():
    return datetime.now(UTC).date()


@router.get("/offers")
async def list_offers(
    offers: Offers, tab: OfferTab | None = None, sort: OfferSort = "fit"
) -> list[OfferListItem]:
    """The offers that have reached the creator, optionally one tab's, sorted."""
    return await offers.list(tab, sort, _today())


@router.get("/offers/counts")
async def offer_counts(offers: Offers) -> OfferCounts:
    """How many offers each tab holds."""
    return await offers.counts()


@router.get("/offers/{thread_id}", responses=OFFER_NOT_FOUND)
async def get_offer(thread_id: UUID, offers: Offers) -> OfferDesk:
    """One offer with its columns, log and the actions open to the creator."""
    try:
        return await offers.desk(thread_id, _today())
    except service.OfferNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from exc


def _error(code: int, name: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(code, detail={"code": name, "message": message, **extra})


async def _act[T](call: Awaitable[T]) -> T:
    """Await a service call, mapping its exceptions to the error contract."""
    try:
        return await call
    except service.OfferNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from exc
    except service.TermsChanged as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "terms_changed",
            "The terms changed while you were looking. Review the latest offer and try again.",
            terms_event_id=exc.latest_event_id,
        ) from exc
    except service.ActionNotAllowed as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "action_not_allowed",
            "That is not possible while the offer is in its current state.",
            status=exc.status,
        ) from exc
    except StaleThread as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "stale_status",
            "The offer moved on while you were acting. Refresh and try again.",
        ) from exc
    except GoLiveInPast as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "go_live_in_past", GoLiveInPast.message
        ) from exc
    except service.BelowFloor as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "below_floor",
            "That price is below your minimum for this package. Confirm to send it anyway.",
            below_by_cents=exc.by_cents,
        ) from exc


@router.post("/offers/{thread_id}/counter/preview", responses=ACTION_ERRORS)
async def preview_counter(
    thread_id: UUID, req: CreatorCounterPreviewRequest, offers: Offers
) -> CreatorCounterPreview:
    """The counter as it would be recorded, its delta, and how far it is below your floor."""
    return await _act(offers.counter_preview(thread_id, req, _today()))


@router.post("/offers/{thread_id}/counter", responses=ACTION_ERRORS)
async def counter_offer(thread_id: UUID, req: CreatorCounterRequest, offers: Offers) -> OfferDesk:
    """Counter the brand's offer, or revise your counter."""
    return await _act(offers.counter(thread_id, req, _today()))


@router.post("/offers/{thread_id}/accept", responses=ACTION_ERRORS)
async def accept_offer(thread_id: UUID, req: AcceptRequest, offers: Offers) -> OfferDesk:
    """Accept the brand's current offer."""
    return await _act(offers.accept(thread_id, req, _today()))


@router.post("/offers/{thread_id}/decline", responses=ACTION_ERRORS)
async def decline_offer(thread_id: UUID, req: DeclineRequest, offers: Offers) -> OfferDesk:
    """Decline the offer, with an optional reason."""
    return await _act(offers.decline(thread_id, req, _today()))

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.adapters.db import Database
from app.api.deps import CurrentUser, get_db, require_role
from app.core.money import format_cents
from app.core.terms import TermsIncomplete
from app.modules.board import actions, service
from app.modules.board.actions import BoardActions
from app.modules.board.service import BoardService
from app.modules.briefs import service as briefs_service
from app.modules.deals import service as deals_service
from app.modules.deals.service import DealsService
from app.schemas.board import (
    BatchListItem,
    BatchView,
    BrandCounterPreview,
    BrandCounterPreviewRequest,
    BrandCounterRequest,
    BrandDeclineRequest,
    DeclineRestPreview,
    DeclineRestResult,
    ResolveRequest,
    ThreadCard,
    ThreadDetail,
)
from app.schemas.deals import AwardPreview, AwardRequest, DealView
from app.workers.runtime import wake_orchestrator

router = APIRouter(tags=["board"])

BATCH_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "`batch_not_found`"}}
THREAD_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "`thread_not_found`"}}


async def my_board(
    user: Annotated[CurrentUser, Depends(require_role("brand"))],
    db: Annotated[Database, Depends(get_db)],
) -> BoardService:
    """The board of the signed-in brand."""
    brand_id = await briefs_service.find_brand_id(db, user.id)
    if brand_id is None:  # a brand profile without its brand row: onboarding never finished
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return BoardService(db, brand_id)


Board = Annotated[BoardService, Depends(my_board)]


@router.get("/batches")
async def list_batches(board: Board) -> list[BatchListItem]:
    """The brand's launched batches, newest first."""
    return await board.list_batches()


@router.get("/batches/{batch_id}", responses=BATCH_NOT_FOUND)
async def get_batch(batch_id: UUID, board: Board) -> BatchView:
    """The batch's cards ranked by best value, with the brief summary and the KPIs."""
    try:
        return await board.batch_view(batch_id)
    except service.BatchNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "batch_not_found") from exc


@router.get("/threads/{thread_id}", responses=THREAD_NOT_FOUND)
async def get_thread(thread_id: UUID, board: Board) -> ThreadDetail:
    """The thread's card with its event log and transcripts."""
    try:
        return await board.thread_detail(thread_id)
    except service.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread_not_found") from exc


@router.post(
    "/threads/{thread_id}/retry",
    responses=THREAD_NOT_FOUND | {status.HTTP_409_CONFLICT: {"description": "`thread_not_failed`"}},
)
async def retry_thread(thread_id: UUID, request: Request, board: Board) -> ThreadCard:
    """Requeue a failed thread; the worker picks it up again."""
    try:
        card = await board.retry(thread_id)
    except service.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread_not_found") from exc
    except service.ThreadNotFailed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "thread_not_failed") from exc
    wake_orchestrator(request.app)
    return card


async def my_actions(
    user: Annotated[CurrentUser, Depends(require_role("brand"))],
    db: Annotated[Database, Depends(get_db)],
) -> BoardActions:
    """The actions of the signed-in brand."""
    brand_id = await briefs_service.find_brand_id(db, user.id)
    if brand_id is None:  # a brand profile without its brand row: onboarding never finished
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return BoardActions(db, brand_id)


Actions = Annotated[BoardActions, Depends(my_actions)]

ACTION_ERRORS = THREAD_NOT_FOUND | {
    status.HTTP_409_CONFLICT: {
        "description": "`terms_changed`, `stale_status`, `action_not_allowed`"
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "`above_ceiling` (counter only)"},
}
AWARD_ERRORS = THREAD_NOT_FOUND | {
    status.HTTP_409_CONFLICT: {
        "description": "`terms_changed`, `stale_status`, `action_not_allowed`"
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "`terms_incomplete`, `milestones_invalid`, `over_ceiling`, `over_target`"
    },
}


async def my_deals(
    user: Annotated[CurrentUser, Depends(require_role("brand"))],
    db: Annotated[Database, Depends(get_db)],
) -> tuple[DealsService, UUID]:
    """The deals service and the id of the signed-in brand."""
    brand_id = await briefs_service.find_brand_id(db, user.id)
    if brand_id is None:  # a brand profile without its brand row: onboarding never finished
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return DealsService(db), brand_id


Deals = Annotated[tuple[DealsService, UUID], Depends(my_deals)]


def _error(code: int, name: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(code, detail={"code": name, "message": message, **extra})


async def _act[T](call: Awaitable[T]) -> T:
    """Await a brand action, mapping its exceptions to the error contract."""
    try:
        return await call
    except service.ThreadNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread_not_found") from exc
    except service.BatchNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "batch_not_found") from exc
    except actions.TermsChanged as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "terms_changed",
            "The terms changed while you were looking. Review the latest and try again.",
            terms_event_id=exc.latest_event_id,
        ) from exc
    except actions.ActionNotAllowed as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "action_not_allowed",
            "That is not possible while the thread is in its current state.",
            status=exc.status,
        ) from exc
    except actions.StaleThread as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "stale_status",
            "The thread moved on while you were acting. Refresh and try again.",
        ) from exc
    except actions.AboveCeiling as exc:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "above_ceiling", exc.message) from exc
    except TermsIncomplete as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "terms_incomplete",
            "Terms incomplete: counter or resolve first.",
        ) from exc
    except deals_service.MilestonesInvalid as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "milestones_invalid",
            "The payment milestones do not fit the agreed terms.",
            errors=exc.errors,
        ) from exc
    except deals_service.OverCeiling as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "over_ceiling",
            f"The agreed price is {format_cents(exc.by_cents)} over your ceiling. "
            "Confirm to award anyway.",
            over_by_cents=exc.by_cents,
        ) from exc
    except deals_service.OverTarget as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "over_target",
            f"You have already hired {exc.hired} of {exc.target}. Confirm to hire more.",
        ) from exc


def _today():
    return datetime.now(UTC).date()


@router.post("/threads/{thread_id}/counter/preview", responses=ACTION_ERRORS)
async def preview_counter(
    thread_id: UUID, req: BrandCounterPreviewRequest, acts: Actions
) -> BrandCounterPreview:
    """The counter as it would be recorded, its delta, and whether it is above your ceiling."""
    return await _act(acts.counter_preview(thread_id, req, _today()))


@router.post("/threads/{thread_id}/counter", responses=ACTION_ERRORS)
async def counter_thread(thread_id: UUID, req: BrandCounterRequest, acts: Actions) -> ThreadCard:
    """Counter the creator's position; the creator is notified."""
    return await _act(acts.counter(thread_id, req, _today()))


@router.post("/threads/{thread_id}/resolve", responses=ACTION_ERRORS)
async def resolve_thread(thread_id: UUID, req: ResolveRequest, acts: Actions) -> ThreadCard:
    """Settle a reply that needed review: record a counter, an acceptance or a decline."""
    return await _act(acts.resolve(thread_id, req, _today()))


@router.post("/threads/{thread_id}/decline", responses=ACTION_ERRORS)
async def decline_thread(thread_id: UUID, req: BrandDeclineRequest, acts: Actions) -> ThreadCard:
    """Withdraw the offer or decline the creator's position; the creator is told politely."""
    return await _act(acts.decline(thread_id, req, _today()))


@router.post("/batches/{batch_id}/decline-rest/preview", responses=BATCH_NOT_FOUND)
async def preview_decline_rest(batch_id: UUID, acts: Actions) -> DeclineRestPreview:
    """The open threads "decline the rest" would close, and the ones it would leave alone."""
    return await _act(acts.decline_rest_preview(batch_id))


@router.post("/batches/{batch_id}/decline-rest", responses=BATCH_NOT_FOUND)
async def decline_rest(batch_id: UUID, acts: Actions) -> DeclineRestResult:
    """Politely close every open thread of the batch; a thread that fails is reported."""
    return await _act(acts.decline_rest(batch_id))


@router.post("/threads/{thread_id}/award/preview", responses=AWARD_ERRORS)
async def preview_award(thread_id: UUID, deals: Deals) -> AwardPreview:
    """The agreed terms, the even milestone split and the confirmations an award would need."""
    service_, brand_id = deals
    return await _act(service_.award_preview(brand_id, thread_id, _today()))


@router.post("/threads/{thread_id}/award", responses=AWARD_ERRORS)
async def award_thread(thread_id: UUID, req: AwardRequest, deals: Deals) -> DealView:
    """Book the deal on the thread's latest terms with the given payment milestones."""
    service_, brand_id = deals
    return await _act(service_.award(brand_id, thread_id, req, _today()))

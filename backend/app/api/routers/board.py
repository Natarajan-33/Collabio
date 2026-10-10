from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.adapters.db import Database
from app.api.deps import CurrentUser, get_db, require_role
from app.modules.board import service
from app.modules.board.service import BoardService
from app.modules.briefs import service as briefs_service
from app.schemas.board import BatchListItem, BatchView, ThreadCard, ThreadDetail
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

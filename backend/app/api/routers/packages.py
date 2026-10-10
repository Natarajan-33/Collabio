from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.adapters.gemini import GeminiPort
from app.api.deps import CurrentUser, get_db, get_gemini, require_role
from app.modules.packages import service
from app.modules.packages.service import PackageService
from app.schemas.my_packages import MyPackage, SavedPackage
from app.schemas.packages import (
    DraftFromSpeechRequest,
    DraftResult,
    FloorRequest,
    PackageDraft,
)

router = APIRouter(prefix="/me/packages", tags=["packages"])

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "`package_not_found`"}}
UNPROCESSABLE = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": (
            "`detail` is `{error: draft_incomplete, missing: [...]}` or "
            "`{error: rules_violated, violations: [{field, message}]}`"
        )
    }
}
VOICE_UNAVAILABLE = {status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "`voice_unavailable`"}}


async def my_packages(
    user: Annotated[CurrentUser, Depends(require_role("creator"))],
    db: Annotated[Database, Depends(get_db)],
) -> PackageService:
    """The package editor for the signed-in creator."""
    creator = await service.find_creator(db, user.id)
    if creator is None:  # a creator profile without its creator row: onboarding never finished
        raise HTTPException(status.HTTP_409_CONFLICT, "onboarding_required")
    return PackageService(db, creator)


Packages = Annotated[PackageService, Depends(my_packages)]
Gemini = Annotated[GeminiPort, Depends(get_gemini)]


@contextmanager
def _http_errors() -> Iterator[None]:
    """Service errors as the responses the editor expects."""
    try:
        yield
    except service.PackageNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "package_not_found") from exc
    except service.DraftIncomplete as exc:
        detail = {"error": "draft_incomplete", "missing": exc.missing}
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from exc
    except service.RulesViolated as exc:
        detail = {
            "error": "rules_violated",
            "violations": [violation.model_dump() for violation in exc.violations],
        }
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from exc
    except service.DraftUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "voice_unavailable") from exc


@router.get("")
async def list_my_packages(packages: Packages) -> list[MyPackage]:
    """The creator's packages, drafts and published, with their private floors."""
    return await packages.list_packages()


@router.post("/draft-from-speech", responses=VOICE_UNAVAILABLE)
async def draft_from_speech(
    req: DraftFromSpeechRequest, packages: Packages, gemini: Gemini
) -> DraftResult:
    """Fold what the creator said into their open draft; nothing is saved.

    When the model's reply is unusable the response is still 200: the draft comes back
    unchanged and `heard` is the raw transcript.
    """
    with _http_errors():
        return await packages.draft_from_speech(gemini, req)


@router.post("", status_code=status.HTTP_201_CREATED, responses=UNPROCESSABLE)
async def create_package(draft: PackageDraft, packages: Packages) -> MyPackage:
    """Save a complete draft as a new unpublished package."""
    with _http_errors():
        return await packages.create(draft)


@router.patch("/{package_id}", responses=NOT_FOUND | UNPROCESSABLE)
async def update_package(
    package_id: UUID, patch: PackageDraft, packages: Packages, gemini: Gemini
) -> SavedPackage:
    """Change the fields sent; fields left out stay as they are. Lists are replaced."""
    with _http_errors():
        return await packages.patch(gemini, package_id, patch)


@router.post("/{package_id}/publish", responses=NOT_FOUND | UNPROCESSABLE)
async def publish_package(package_id: UUID, packages: Packages, gemini: Gemini) -> SavedPackage:
    """Publish the package to brands and refresh the creator's search embedding.

    If the embedding cannot be refreshed the package is still published and `warnings`
    says the search index update is pending.
    """
    with _http_errors():
        return await packages.publish(gemini, package_id)


@router.put("/{package_id}/floor", responses=NOT_FOUND | UNPROCESSABLE)
async def set_package_floor(package_id: UUID, req: FloorRequest, packages: Packages) -> MyPackage:
    """Set the private lowest price the creator accepts; never shown to brands."""
    with _http_errors():
        return await packages.set_floor(package_id, req.floor_price_cents)

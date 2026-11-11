"""Hackathon demo helpers: restore the seeded money deals."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.db import Database
from app.api.deps import CurrentUser, get_db, onboarded_user
from app.config import Settings, get_settings
from scripts.seed_money import seed_money

router = APIRouter(tags=["demo"])

RESET_EVERY_S = 60
_last_reset = {"at": 0.0}


@router.post("/demo/reset")
async def reset_demo(
    _user: Annotated[CurrentUser, Depends(onboarded_user)],
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Recreate the three demo deals (hackathon mode only, at most once a minute)."""
    if not settings.hackathon_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    personas = {settings.demo_brand_email.lower(), settings.demo_helper_email.lower()}
    if (_user.email or "").lower() not in personas:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "demo_personas_only")
    now = time.monotonic()
    if now - _last_reset["at"] < RESET_EVERY_S:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "reset_too_soon")
    _last_reset["at"] = now
    async with db.acquire() as conn:
        ids = await seed_money(conn)
    return {title: str(deal_id) for title, deal_id in ids.items()}

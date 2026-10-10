"""One-click unsubscribe from an outreach email. No sign-in: the reply token is the credential."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.adapters.db import Database
from app.api.deps import get_db

router = APIRouter(tags=["unsubscribe"])

PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>Unsubscribed</title></head>"
    '<body style="font-family:system-ui,sans-serif;max-width:480px;margin:15vh auto;padding:0 16px">'
    "<h1>You're unsubscribed</h1><p>Brands on Collabio won't contact you again.</p>"
    "</body></html>"
)
OPT_OUT = """
update public.creators set contact_opt_out = true
where id = (select creator_id from public.threads where reply_token = $1)
"""


async def _unsubscribe(db: Database, reply_token: str) -> HTMLResponse:
    """Opt out the thread's creator. An unknown token gets the same page, so tokens cannot be
    probed."""
    async with db.acquire() as conn:
        await conn.execute(OPT_OUT, reply_token)
    return HTMLResponse(PAGE)


# GET is the link in the email; POST is the mail client's one-click List-Unsubscribe-Post.
@router.get("/unsubscribe/{reply_token}", response_class=HTMLResponse)
async def unsubscribe_get(
    reply_token: str, db: Annotated[Database, Depends(get_db)]
) -> HTMLResponse:
    return await _unsubscribe(db, reply_token)


@router.post("/unsubscribe/{reply_token}", response_class=HTMLResponse)
async def unsubscribe_post(
    reply_token: str, db: Annotated[Database, Depends(get_db)]
) -> HTMLResponse:
    return await _unsubscribe(db, reply_token)

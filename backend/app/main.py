import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.db import Database
from app.api.routers import creators, discovery, health, me
from app.config import get_settings

API_PREFIX = "/api/v1"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the process-wide database pool, when a database is configured."""
    settings = get_settings()
    if not settings.database_configured:
        logger.warning(
            "SUPABASE_DB_URL is not configured: endpoints that need the database return 503"
        )
        yield
        return

    db = Database()
    await db.connect(settings.supabase_db_url)
    app.state.db = db
    try:
        yield
    finally:
        app.state.db = None
        await db.close()


def create_app() -> FastAPI:
    """Build the FastAPI app. Run with `uvicorn app.main:create_app --factory`."""
    settings = get_settings()

    app = FastAPI(title="Collabio API", version="0.1.0", lifespan=lifespan)
    app.state.db = None  # set by the lifespan; see app.api.deps.get_db
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(me.router)
    api.include_router(discovery.router)
    api.include_router(creators.router)
    app.include_router(api)

    return app

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.db import Database
from app.api.routers import (
    board,
    briefs,
    creators,
    discovery,
    health,
    me,
    packages,
    unsubscribe,
    voice,
    webhooks,
)
from app.config import get_settings
from app.workers.runtime import start_workers, stop_workers

API_PREFIX = "/api/v1"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the process-wide database pool, when a database is configured, and run the launch
    workers on it unless `WORKERS_ENABLED` is off."""
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
        if settings.workers_enabled:
            await start_workers(app, settings)
        yield
    finally:
        if app.state.workers is not None:
            await stop_workers(app)
        app.state.db = None
        await db.close()


def create_app() -> FastAPI:
    """Build the FastAPI app. Run with `uvicorn app.main:create_app --factory`."""
    settings = get_settings()

    app = FastAPI(title="Collabio API", version="0.1.0", lifespan=lifespan)
    app.state.db = None  # set by the lifespan; see app.api.deps.get_db
    app.state.workers = None  # set by the lifespan when workers are enabled
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(me.router)
    api.include_router(discovery.router)
    api.include_router(creators.router)
    api.include_router(packages.router)
    api.include_router(voice.router)
    api.include_router(briefs.router)
    api.include_router(board.router)
    api.include_router(unsubscribe.router)
    api.include_router(webhooks.router)
    app.include_router(api)

    return app

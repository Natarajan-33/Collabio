from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import health
from app.config import get_settings

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Build the FastAPI app. Run with `uvicorn app.main:create_app --factory`."""
    settings = get_settings()

    app = FastAPI(title="Collabio API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    app.include_router(api)

    return app

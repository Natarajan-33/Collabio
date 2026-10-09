"""The app lifespan opens the database pool only when a database is configured."""

from uuid import uuid4

import pytest

from app.config import Settings, get_settings
from tests.tokens import auth_header

PLACEHOLDER_DSN = "postgresql://postgres:[YOUR-PASSWORD]@db.example.invalid:5432/postgres"


@pytest.mark.parametrize(
    ("dsn", "configured"),
    [
        pytest.param("", False, id="empty"),
        pytest.param("   ", False, id="blank"),
        pytest.param(PLACEHOLDER_DSN, False, id="placeholder"),
        pytest.param(
            "postgresql://postgres:secret@db.example.invalid:5432/postgres", True, id="real"
        ),
    ],
)
def test_database_configured(dsn, configured):
    assert Settings(supabase_db_url=dsn).database_configured is configured


@pytest.fixture
def no_database(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", PLACEHOLDER_DSN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_app_starts_without_a_database(no_database, app, client, fake_jwks):
    async with app.router.lifespan_context(app):
        assert app.state.db is None
        r = await client.get("/api/v1/me", headers=auth_header(uuid4()))
    # The token verified; the request then needed the database.
    assert r.status_code == 503
    assert r.json() == {"detail": "database_unavailable"}


@pytest.mark.db
async def test_lifespan_opens_and_closes_the_pool(app, db):
    # `db` makes this skip when no database is reachable; the lifespan opens its own pool.
    async with app.router.lifespan_context(app), app.state.db.acquire() as conn:
        assert await conn.fetchval("select 1") == 1
    assert app.state.db is None

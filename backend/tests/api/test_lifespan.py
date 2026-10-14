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


@pytest.fixture
def worker_calls(monkeypatch):
    """Replace start_workers/stop_workers in the lifespan with recorders, so no orchestrator
    ever runs against the shared database."""
    calls: list[str] = []

    async def start(app, settings):
        calls.append("start")
        app.state.workers = object()

    async def stop(app):
        calls.append("stop")
        app.state.workers = None

    monkeypatch.setattr("app.main.start_workers", start)
    monkeypatch.setattr("app.main.stop_workers", stop)
    return calls


def settings_with_workers(monkeypatch, value: str) -> None:
    monkeypatch.setenv("WORKERS_ENABLED", value)
    get_settings.cache_clear()


@pytest.mark.db
async def test_workers_not_started_when_disabled(app, db, monkeypatch, worker_calls):
    settings_with_workers(monkeypatch, "0")
    try:
        async with app.router.lifespan_context(app):
            assert app.state.workers is None
    finally:
        get_settings.cache_clear()
    assert worker_calls == []


@pytest.mark.db
async def test_lifespan_starts_and_stops_workers(app, db, monkeypatch, worker_calls):
    settings_with_workers(monkeypatch, "1")
    try:
        async with app.router.lifespan_context(app):
            assert worker_calls == ["start"]
            assert app.state.workers is not None
            assert app.state.db is not None
    finally:
        get_settings.cache_clear()
    assert worker_calls == ["start", "stop"]
    assert app.state.workers is None


def test_the_suite_runs_with_workers_off():
    """conftest forces WORKERS_ENABLED=0, so a lifespan in any other test starts no worker."""
    assert get_settings().workers_enabled is False


async def test_start_workers_runs_the_m3_workers(monkeypatch):
    """The real `start_workers` adds the outbox sender and the expiry sweep. Every loop and the
    orchestrator are replaced by a sleeper, so nothing touches a database."""
    import asyncio

    from fastapi import FastAPI

    from app.workers import runtime

    started: dict[str, dict] = {}

    def sleeper(name):
        async def run(*args, **kwargs):
            started[name] = kwargs
            await asyncio.sleep(3600)

        return run

    class FakeOrchestrator:
        def __init__(self, db, handlers):
            pass

        async def run(self):
            await asyncio.sleep(3600)

        def wake(self):
            pass

    async def no_sweep(db):
        return None

    monkeypatch.setattr(runtime, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(runtime, "sweep_stuck", no_sweep)
    monkeypatch.setattr(runtime, "sweep_loop", sleeper("sweep"))
    monkeypatch.setattr(runtime, "outbox_loop", sleeper("outbox"))
    monkeypatch.setattr(runtime, "expiry_loop", sleeper("expiry"))
    app = FastAPI()
    app.state.db = object()
    settings = Settings(_env_file=None, resend_api_key="")

    await runtime.start_workers(app, settings)
    try:
        await asyncio.sleep(0)  # let the tasks start
        names = {task.get_name() for task in app.state.workers.tasks}
        assert {"outbox-sender", "expiry-sweep"} <= names
        assert started["outbox"]["gemini"] is None
        assert started["outbox"]["settings"] is settings
        # Built on first use: without a Resend key, starting the worker must not fail.
        with pytest.raises(ValueError):
            started["outbox"]["email"]()
    finally:
        await runtime.stop_workers(app)
    assert app.state.workers is None

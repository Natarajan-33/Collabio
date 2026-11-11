"""Render Workflows service for Claude settlement runs (spec §8, plan Task 16).

Two tasks, both calling the same service code as the API:
- `settle_submission(submission_id)`: one settlement run (idempotent per submission);
- `nightly_settlement()`: sync payouts and re-run stuck settlements.

Start command on Render (root dir `backend`): `uv run --no-sync python -m workflows.settlement`.
The API triggers `settle_submission` when `RENDER_WORKFLOWS_ENABLED=1` (app/modules/money/runner.py).
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from render import Retry, Workflows
from render.workflows.context import TaskContext

from app.adapters.claude import ClaudeClient
from app.adapters.db import Database
from app.adapters.paypal import PayPalClient
from app.adapters.storage import Storage
from app.config import get_settings
from app.modules.money.service import MoneyService

app = Workflows(
    default_retry=Retry(max_retries=2, wait_duration_ms=2000, backoff_scaling=2.0),
    default_timeout=600,
)


async def with_money(fn: Callable[[MoneyService], Awaitable[Any]]) -> Any:
    """Build a MoneyService from env for one task run, and close its pool afterwards."""
    settings = get_settings()
    db = Database()
    await db.connect(settings.supabase_db_url, min_size=1, max_size=3)
    try:
        money = MoneyService(
            db,
            PayPalClient(
                settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url
            ),
            ClaudeClient(settings.anthropic_api_key),
            settings,
            Storage(settings.supabase_url, settings.supabase_secret_key),
        )
        return await fn(money)
    finally:
        await db.close()


@app.task
async def settle_submission(ctx: TaskContext, submission_id: str) -> str:
    """One Claude settlement run for a proof submission; returns the run's outcome."""
    return await with_money(lambda money: money.settle(UUID(submission_id)))


async def _nightly(money: MoneyService) -> dict[str, int]:
    stale: list[UUID] = []
    result = await money.nightly(stale.append)
    for submission_id in stale:
        await money.settle(submission_id)
    return result


@app.task
async def nightly_settlement(ctx: TaskContext) -> dict[str, int]:
    """Sync sent/approved payouts with PayPal and re-run settlement runs that errored."""
    return await with_money(_nightly)


if __name__ == "__main__":
    app.start()

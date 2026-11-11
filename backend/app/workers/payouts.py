"""Polls PayPal for `sent` payouts every 30 s (webhooks cannot reach a laptop)."""

import asyncio
import logging

from app.adapters.db import Database
from app.adapters.paypal import PayPalClient
from app.config import Settings
from app.modules.money.service import MoneyService

logger = logging.getLogger(__name__)

POLL_SECONDS = 30


async def run_payout_sync(db: Database, settings: Settings) -> None:
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        logger.warning("PayPal is not configured: payout status sync is off")
        return
    paypal = PayPalClient(
        settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url
    )
    service = MoneyService(db, paypal, None, settings)
    while True:
        try:
            await service.sync_sent_payouts()
        except Exception:
            logger.exception("payout sync failed")
        await asyncio.sleep(POLL_SECONDS)

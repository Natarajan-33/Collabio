"""The notification outbox writer.

`enqueue` runs in the caller's transaction, next to the event it announces, so a committed
action always has its notification queued and a rolled-back one never does. The sender
(`app.modules.notify.sender`) delivers the rows later, so an action never waits on Resend.
"""

import json
from typing import Literal
from uuid import UUID

import asyncpg

OutboxKind = Literal[
    "creator_brand_countered",
    "creator_awarded",
    "creator_closed",
    "brand_creator_countered",
    "brand_creator_accepted",
    "brand_creator_declined",
    "brand_needs_review",
]

INSERT_OUTBOX = """
insert into public.outbox_emails (kind, thread_id, event_id, to_role, payload)
values ($1, $2, $3, $4, $5::jsonb)
on conflict (kind, event_id) do nothing
"""


async def enqueue(
    conn: asyncpg.Connection,
    *,
    kind: OutboxKind,
    thread_id: UUID,
    event_id: int,
    payload: dict | None = None,
) -> None:
    """Queue a notification about `event_id`; the recipient is the kind's prefix.

    Queuing the same `(kind, event_id)` twice leaves one row. The payload must not carry a
    private limit (a creator's floor or a brand's ceiling), in cents or in dollars.
    """
    to_role = kind.split("_", 1)[0]
    await conn.execute(INSERT_OUTBOX, kind, thread_id, event_id, to_role, json.dumps(payload or {}))

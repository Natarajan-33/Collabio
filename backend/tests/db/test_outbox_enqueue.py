"""The outbox writer: the recipient comes from the kind, and one event notifies once."""

import json

import pytest

from app.modules.notify.outbox import enqueue
from tests.db.test_thread_repo import make_thread

pytestmark = pytest.mark.db


async def test_enqueue_sets_role_and_is_idempotent(db_conn, factory):
    thread = await make_thread(factory, status="countered")
    event_id = await factory.event(thread.id, "counter_submitted", actor="creator")

    await enqueue(
        db_conn,
        kind="brand_creator_countered",
        thread_id=thread.id,
        event_id=event_id,
        payload={"note": "hi"},
    )
    await enqueue(db_conn, kind="brand_creator_countered", thread_id=thread.id, event_id=event_id)

    rows = await db_conn.fetch(
        "select kind, to_role, status, attempts, payload from public.outbox_emails"
        " where thread_id = $1",
        thread.id,
    )
    assert len(rows) == 1
    assert (rows[0]["kind"], rows[0]["to_role"]) == ("brand_creator_countered", "brand")
    assert (rows[0]["status"], rows[0]["attempts"]) == ("pending", 0)
    assert json.loads(rows[0]["payload"]) == {"note": "hi"}


async def test_enqueue_creator_kinds_go_to_creator(db_conn, factory):
    thread = await make_thread(factory, status="awaiting_reply")
    event_id = await factory.event(thread.id, "brand_counter_sent", actor="brand")

    await enqueue(db_conn, kind="creator_brand_countered", thread_id=thread.id, event_id=event_id)

    role = await db_conn.fetchval(
        "select to_role from public.outbox_emails where thread_id = $1", thread.id
    )
    assert role == "creator"

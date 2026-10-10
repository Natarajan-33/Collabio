"""GET/POST /unsubscribe/{reply_token}: one click opts the creator out of brand contact."""

import pytest

pytestmark = pytest.mark.db

PAGE = "<h1>You're unsubscribed</h1><p>Brands on Collabio won't contact you again.</p>"


@pytest.mark.parametrize("method", ["get", "post"])
async def test_unsubscribe_sets_opt_out(client, api_db, launched_batch, method):
    thread_id = launched_batch.threads["mayamakestech"]
    async with api_db.acquire() as conn:
        row = await conn.fetchrow(
            "select t.reply_token, c.id, c.contact_opt_out from public.threads t"
            " join public.creators c on c.id = t.creator_id where t.id = $1",
            thread_id,
        )
    try:
        r = await getattr(client, method)(f"/api/v1/unsubscribe/{row['reply_token']}")

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert PAGE in r.text
        async with api_db.acquire() as conn:
            opted_out = await conn.fetchval(
                "select contact_opt_out from public.creators where id = $1", row["id"]
            )
        assert opted_out is True
    finally:
        async with api_db.acquire() as conn:
            await conn.execute(
                "update public.creators set contact_opt_out = $2 where id = $1",
                row["id"],
                row["contact_opt_out"],
            )


async def test_unsubscribe_unknown_token_shows_same_page(client, api_db):
    r = await client.get("/api/v1/unsubscribe/not-a-real-token")

    assert r.status_code == 200
    assert PAGE in r.text

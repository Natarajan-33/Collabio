"""Seeds the demo marketplace: 40 fictional creators, a demo brand and two demo creators.

    uv run python -m scripts.seed --reset

Two steps, so tests can run the database half inside a rolled-back transaction:

* `ensure_demo_users` creates (or resets the password of) the three demo logins through
  the Supabase Auth Admin API.
* `seed_marketplace` replaces the Collabio rows of the seeded creators and the demo
  accounts, and loads each creator's embedding from the committed cache. It never calls
  Gemini (`scripts.build_embedding_cache` does) and never touches `auth.users`.
* `delete_leftover_test_users` also clears the throwaway logins that interrupted test runs
  leave behind (`<id>@test.collabio.invalid`), and nobody else.

The demo accounts come from DEMO_* in backend/.env; the three logins share DEMO_PASSWORD.
"""

import argparse
import asyncio
import json
import re
import sys
import uuid
from dataclasses import dataclass

import asyncpg
import httpx

from app.adapters.db import Database
from app.config import Settings, get_settings
from scripts.seed_data import Creator, Embeddings, embedding_hash, load_creators, load_embeddings

ARJUN_HANDLE = "arjuntech"
PRIYA_HANDLE = "priyareviews"

DEMO_COMPANY = "Lumen Audio"
DEMO_CATEGORY = "consumer_tech"
DEMO_PRODUCT = "Lumen Pods"
DEMO_PRODUCT_SUMMARY = "Wireless earbuds with 40-hour battery and adaptive noise cancelling"

# Seeded rows get ids derived from their handle, so they survive a re-seed unchanged.
SEED_NAMESPACE = uuid.UUID("5d0f6c1e-2b7a-4c3e-9a41-0c0ffee0ab10")
SEEDED_EMAIL_PATTERN = "%@example.com"
# The throwaway logins the tests create (tests/conftest.py, tests/db/conftest.py).
TEST_USER_EMAIL_PATTERN = "%@test.collabio.invalid"
E164 = re.compile(r"^\+[1-9][0-9]{1,14}$")

ADMIN_USERS_PATH = "/auth/v1/admin/users"
ADMIN_USERS_PAGE_SIZE = 200
HTTP_TIMEOUT_SECONDS = 30.0

DEMO_ENV_VARS = ("DEMO_BRAND_EMAIL", "DEMO_PASSWORD", "DEMO_HELPER_EMAIL", "DEMO_HELPER_PHONE")


class SeedError(Exception):
    """The seed cannot run or finish; the message says what to fix."""


@dataclass(frozen=True)
class DemoUser:
    id: uuid.UUID
    email: str


@dataclass(frozen=True)
class DemoAccounts:
    """The three demo logins. `phone` is Arjun's contact number (E.164)."""

    brand: DemoUser
    priya: DemoUser
    arjun: DemoUser
    phone: str

    @property
    def user_ids(self) -> list[uuid.UUID]:
        return [self.brand.id, self.priya.id, self.arjun.id]


def plus_address(email: str, tag: str) -> str:
    """`a.b@x.com` + `arjun` -> `a.b+arjun@x.com`: a second inbox on the same mailbox."""
    local, _, domain = email.partition("@")
    return f"{local}+{tag}@{domain}"


# Demo users (Supabase Auth Admin API) ---------------------------------------------


def missing_demo_settings(settings: Settings) -> list[str]:
    """Names of the DEMO_* variables (and the keys the seed needs) that are not set."""
    values = {
        "SUPABASE_SECRET_KEY": settings.supabase_secret_key,
        "DEMO_BRAND_EMAIL": settings.demo_brand_email,
        "DEMO_PASSWORD": settings.demo_password,
        "DEMO_HELPER_EMAIL": settings.demo_helper_email,
        "DEMO_HELPER_PHONE": settings.demo_helper_phone,
    }
    return [name for name, value in values.items() if not value.strip()]


async def ensure_demo_users(settings: Settings) -> DemoAccounts:
    """Create the brand and the two creators as confirmed Auth users, or, when an email is
    already registered, reset that user's password. Returns their ids."""
    if missing := missing_demo_settings(settings):
        raise SeedError(f"Set {', '.join(missing)} in backend/.env first.")
    if not E164.match(settings.demo_helper_phone):
        raise SeedError("DEMO_HELPER_PHONE must be in E.164 form, e.g. +14155550123.")
    emails = {
        "brand": settings.demo_brand_email.strip(),
        "priya": settings.demo_helper_email.strip(),
        "arjun": plus_address(settings.demo_helper_email.strip(), "arjun"),
    }
    # Secret keys (sb_secret_...) are not JWTs: the gateway takes them on `apikey` alone.
    async with httpx.AsyncClient(
        base_url=settings.supabase_url,
        headers={"apikey": settings.supabase_secret_key},
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as http:
        ids = {
            key: await _ensure_user(http, email, settings.demo_password)
            for key, email in emails.items()
        }
    return DemoAccounts(
        brand=DemoUser(ids["brand"], emails["brand"]),
        priya=DemoUser(ids["priya"], emails["priya"]),
        arjun=DemoUser(ids["arjun"], emails["arjun"]),
        phone=settings.demo_helper_phone,
    )


async def _ensure_user(http: httpx.AsyncClient, email: str, password: str) -> uuid.UUID:
    created = await http.post(
        ADMIN_USERS_PATH, json={"email": email, "password": password, "email_confirm": True}
    )
    if created.is_success:
        return uuid.UUID(created.json()["id"])
    if created.status_code == 422 and _body(created).get("error_code") == "email_exists":
        user_id = await _find_user_id(http, email)
        updated = await http.put(
            f"{ADMIN_USERS_PATH}/{user_id}", json={"password": password, "email_confirm": True}
        )
        if not updated.is_success:
            raise _auth_error(updated, "reset the password of an existing demo user")
        return user_id
    raise _auth_error(created, "create a demo user")


async def _find_user_id(http: httpx.AsyncClient, email: str) -> uuid.UUID:
    """The id of the registered user with this email (the admin API cannot filter by email)."""
    page = 1
    while True:
        response = await http.get(
            ADMIN_USERS_PATH, params={"page": page, "per_page": ADMIN_USERS_PAGE_SIZE}
        )
        if not response.is_success:
            raise _auth_error(response, "list users")
        users = response.json()["users"]
        for user in users:
            if (user.get("email") or "").casefold() == email.casefold():
                return uuid.UUID(user["id"])
        if len(users) < ADMIN_USERS_PAGE_SIZE:
            raise SeedError("An email is registered but missing from the Auth user list.")
        page += 1


def _body(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _auth_error(response: httpx.Response, action: str) -> SeedError:
    body = _body(response)
    detail = body.get("msg") or body.get("error_code") or ""
    return SeedError(
        f"Supabase Auth could not {action}: HTTP {response.status_code} {detail}".strip()
    )


# Marketplace rows (database) -------------------------------------------------------

DELETE_DEMO_PROFILES = "delete from public.profiles where id = any($1::uuid[])"
# Seeded creators have no login; the demo creators are removed with their profiles above
# and by handle, in case they were seeded without a login before.
DELETE_SEEDED_CREATORS = """
delete from public.creators
where handle = any($1::text[])
   or (profile_id is null and email like $2)
"""
# Deleting a login cascades to its profile and the brand, products or creator row under it.
# The demo logins are kept even if their email happens to be on the test domain.
DELETE_TEST_USERS = """
delete from auth.users
where email like $1 and id <> all($2::uuid[])
returning id
"""
INSERT_PROFILE = "insert into public.profiles (id, role, display_name) values ($1, $2, $3)"
INSERT_BRAND = """
insert into public.brands (profile_id, company_name, category, contact_email)
values ($1, $2, $3, $4)
returning id
"""
INSERT_PRODUCT = (
    "insert into public.products (brand_id, name, summary, category) values ($1, $2, $3, $4)"
)
INSERT_CREATORS = """
insert into public.creators
  (id, profile_id, handle, name, bio, niches, platforms, region, languages, followers,
   engagement_rate, email, phone, phone_opt_in, embedding, embedding_text_hash)
values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
"""
INSERT_PACKAGES = """
insert into public.packages
  (id, creator_id, name, content_type, niche, volume_count, volume_basis, base_price_cents,
   currency, included, freebies, addons, extras, slots_per_month, lead_time_days,
   preferred_channel, status)
values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
"""
INSERT_FLOORS = "insert into public.package_floors (package_id, floor_price_cents) values ($1, $2)"


def require_cached_embeddings(creators: list[Creator], cache: Embeddings) -> None:
    for creator in creators:
        if embedding_hash(creator) not in cache:
            raise SeedError(
                f"embedding cache stale for {creator['handle']} — run scripts.build_embedding_cache"
            )


async def seed_marketplace(
    conn: asyncpg.Connection,
    creators: list[Creator],
    cache: Embeddings,
    demo: DemoAccounts | None,
) -> int:
    """Replace the seeded marketplace inside the caller's transaction; returns the creator count.

    Deletes, then reinserts: the seeded creators (and their packages and floors), and the
    demo accounts' profiles, brand, product and creator rows. Other users' rows and
    `auth.users` are untouched. With `demo`, Priya and Arjun are linked to their logins and
    the demo brand and its product are created; without it they are plain seeded creators.
    """
    require_cached_embeddings(creators, cache)
    demo_creators = _demo_creator_overrides(demo)

    await conn.execute(DELETE_DEMO_PROFILES, demo.user_ids if demo else [])
    await conn.execute(
        DELETE_SEEDED_CREATORS, [c["handle"] for c in creators], SEEDED_EMAIL_PATTERN
    )

    if demo is not None:
        await _insert_demo_accounts(conn, demo)

    creator_rows, package_rows, floor_rows = [], [], []
    for creator in creators:
        creator_id = _seed_id(creator["handle"])
        override = demo_creators.get(creator["handle"], {})
        text_hash = embedding_hash(creator)
        phone = override.get("phone", creator["phone"])
        creator_rows.append(
            (
                creator_id,
                override.get("profile_id"),
                creator["handle"],
                creator["name"],
                creator["bio"],
                creator["niches"],
                json.dumps(creator["platforms"]),
                creator["region"],
                creator["languages"],
                creator["followers"],
                creator["engagement_rate"],
                override.get("email", creator["email"]),
                phone,
                bool(creator["phone_opt_in"] and phone),
                cache[text_hash],
                text_hash,
            )
        )
        for package in creator["packages"]:
            package_id = _seed_id(creator["handle"], package["name"])
            package_rows.append(
                (
                    package_id,
                    creator_id,
                    package["name"],
                    package["content_type"],
                    package["niche"],
                    package["volume_count"],
                    package["volume_basis"],
                    package["base_price_cents"],
                    package["currency"],
                    package["included"],
                    package["freebies"],
                    json.dumps(package["addons"]),
                    json.dumps(package["extras"]),
                    package["slots_per_month"],
                    package["lead_time_days"],
                    package["preferred_channel"],
                    package["status"],
                )
            )
            floor_rows.append((package_id, package["floor_price_cents"]))

    await conn.executemany(INSERT_CREATORS, creator_rows)
    await conn.executemany(INSERT_PACKAGES, package_rows)
    await conn.executemany(INSERT_FLOORS, floor_rows)
    return len(creator_rows)


async def delete_leftover_test_users(conn: asyncpg.Connection, keep: list[uuid.UUID]) -> int:
    """Delete the throwaway test logins left in `auth.users`; returns how many.

    Only emails ending in `@test.collabio.invalid` go, and never the ids in `keep` (the demo
    logins). Runs in the caller's transaction. It is a step of its own: `seed_marketplace`
    leaves every user's rows alone.
    """
    rows = await conn.fetch(DELETE_TEST_USERS, TEST_USER_EMAIL_PATTERN, keep)
    return len(rows)


def _seed_id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, "/".join(parts))


def _demo_creator_overrides(demo: DemoAccounts | None) -> dict[str, dict]:
    """Per demo creator: the login they are linked to and the contact details to use."""
    if demo is None:
        return {}
    return {
        PRIYA_HANDLE: {"profile_id": demo.priya.id, "email": demo.priya.email},
        ARJUN_HANDLE: {
            "profile_id": demo.arjun.id,
            "email": demo.arjun.email,
            "phone": demo.phone,
        },
    }


async def _insert_demo_accounts(conn: asyncpg.Connection, demo: DemoAccounts) -> None:
    await conn.execute(INSERT_PROFILE, demo.brand.id, "brand", DEMO_COMPANY)
    await conn.execute(INSERT_PROFILE, demo.priya.id, "creator", "Priya Raman")
    await conn.execute(INSERT_PROFILE, demo.arjun.id, "creator", "Arjun Mehta")
    brand_id = await conn.fetchval(
        INSERT_BRAND, demo.brand.id, DEMO_COMPANY, DEMO_CATEGORY, demo.brand.email
    )
    await conn.execute(INSERT_PRODUCT, brand_id, DEMO_PRODUCT, DEMO_PRODUCT_SUMMARY, DEMO_CATEGORY)


# CLI ---------------------------------------------------------------------------------


async def run(settings: Settings) -> str:
    """Create the demo users, then replace the marketplace in one transaction."""
    creators, cache = load_creators(), load_embeddings()
    require_cached_embeddings(creators, cache)  # fail before creating any Auth user
    if not settings.database_configured:
        raise SeedError("Set SUPABASE_DB_URL in backend/.env first.")
    demo = await ensure_demo_users(settings)
    db = Database()
    await db.connect(settings.supabase_db_url, max_size=1)
    try:
        async with db.transaction() as conn:
            removed = await delete_leftover_test_users(conn, demo.user_ids)
            count = await seed_marketplace(conn, creators, cache, demo)
    finally:
        await db.close()
    message = f"seeded {count} creators, 3 demo accounts"
    return f"{message}, removed {removed} leftover test users" if removed else message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.seed",
        description="Replace the seeded marketplace and demo accounts in the hosted database.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="confirm that the seeded creators, the demo accounts' rows and leftover test "
        "logins (@test.collabio.invalid) are deleted first",
    )
    args = parser.parse_args(argv)
    if not args.reset:
        parser.error("seeding deletes and reloads the seeded rows; pass --reset to confirm")

    settings = get_settings()
    if missing := missing_demo_settings(settings):
        print(f"Cannot seed: set {', '.join(missing)} in backend/.env first.", file=sys.stderr)
        return 1
    try:
        print(asyncio.run(run(settings)))
    except SeedError as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

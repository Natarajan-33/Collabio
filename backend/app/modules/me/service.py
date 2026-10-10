"""The signed-in user's account: reading it, and onboarding into a role.

The database connection is privileged (no RLS), so every statement here is scoped
to the caller's own user id.
"""

from uuid import UUID

import asyncpg

from app.adapters.db import Database
from app.schemas.me import (
    BrandOnboarding,
    BrandSummary,
    CreatorOnboarding,
    CreatorSummary,
    MeResponse,
    OnboardingRequest,
    Role,
)


class RoleLocked(Exception):
    """The user already onboarded with the other role."""


class HandleTaken(Exception):
    """Another creator already has the requested handle."""


SELECT_ROLE = "select role from public.profiles where id = $1"

SELECT_ME = """
select p.role, p.display_name,
       b.id as brand_id, b.company_name, b.category,
       c.id as creator_id, c.handle, c.name as creator_name, c.niches, c.region
from public.profiles p
left join lateral (
  select id, company_name, category
  from public.brands
  where profile_id = p.id
  order by id
  limit 1
) b on true
left join public.creators c on c.profile_id = p.id
where p.id = $1
"""

# Inserts the profile, or renames it when it already has this role. A profile with
# the other role is left untouched and no row is returned.
UPSERT_PROFILE = """
insert into public.profiles (id, role, display_name)
values ($1, $2, $3)
on conflict (id) do update set display_name = excluded.display_name
  where profiles.role = excluded.role
returning id
"""

SELECT_BRAND_ID = "select id from public.brands where profile_id = $1 order by id limit 1"
INSERT_BRAND = """
insert into public.brands (profile_id, company_name, category, contact_email)
values ($1, $2, $3, $4)
returning id
"""
UPDATE_BRAND = """
update public.brands
set company_name = $2, category = $3, contact_email = coalesce(contact_email, $4)
where id = $1
"""
# The product named at onboarding: added only while the brand has none, so a
# repeated onboarding never duplicates it.
INSERT_FIRST_PRODUCT = """
insert into public.products (brand_id, name, summary, category)
select $1::uuid, $2::text, $3::text, $4::text
where not exists (select 1 from public.products where brand_id = $1::uuid)
"""

UPSERT_CREATOR = """
insert into public.creators (profile_id, handle, name, niches, region, email)
values ($1, $2, $3, $4, $5, $6)
on conflict (profile_id) do update set
  handle = excluded.handle,
  name = excluded.name,
  niches = excluded.niches,
  region = excluded.region,
  email = coalesce(creators.email, excluded.email)
"""
CREATORS_HANDLE_KEY = "creators_handle_key"


async def get_role(db: Database, user_id: UUID) -> Role | None:
    async with db.acquire() as conn:
        return await conn.fetchval(SELECT_ROLE, user_id)


async def get_me(db: Database, user_id: UUID, email: str | None) -> MeResponse:
    async with db.acquire() as conn:
        return await _load_me(conn, user_id, email)


async def onboard(
    db: Database, user_id: UUID, email: str | None, req: OnboardingRequest
) -> MeResponse:
    """Give the user a role plus its brand (and product) or creator row, atomically.

    Onboarding again with the same role updates the names and details; the product
    is created only once. Onboarding with the other role raises `RoleLocked`. The
    brand's contact email and the creator's email default to the sign-in `email`.
    """
    try:
        async with db.transaction() as conn:
            if await conn.fetchval(UPSERT_PROFILE, user_id, req.role, req.display_name) is None:
                raise RoleLocked
            if isinstance(req, BrandOnboarding):
                await _save_brand(conn, user_id, email, req)
            else:
                await _save_creator(conn, user_id, email, req)
            return await _load_me(conn, user_id, email)
    except asyncpg.UniqueViolationError as exc:
        if exc.constraint_name == CREATORS_HANDLE_KEY:
            raise HandleTaken from exc
        raise


async def _save_brand(
    conn: asyncpg.Connection, user_id: UUID, email: str | None, req: BrandOnboarding
) -> None:
    brand_id = await conn.fetchval(SELECT_BRAND_ID, user_id)
    if brand_id is None:
        brand_id = await conn.fetchval(INSERT_BRAND, user_id, req.company_name, req.category, email)
    else:
        await conn.execute(UPDATE_BRAND, brand_id, req.company_name, req.category, email)
    await conn.execute(
        INSERT_FIRST_PRODUCT, brand_id, req.product_name, req.product_summary, req.category
    )


async def _save_creator(
    conn: asyncpg.Connection, user_id: UUID, email: str | None, req: CreatorOnboarding
) -> None:
    await conn.execute(
        UPSERT_CREATOR, user_id, req.handle, req.display_name, req.niches, req.region, email
    )


async def _load_me(conn: asyncpg.Connection, user_id: UUID, email: str | None) -> MeResponse:
    row = await conn.fetchrow(SELECT_ME, user_id)
    if row is None:
        return MeResponse(
            user_id=user_id, email=email, role=None, display_name=None, brand=None, creator=None
        )
    brand = None
    if row["brand_id"] is not None:
        brand = BrandSummary(
            id=row["brand_id"], company_name=row["company_name"], category=row["category"]
        )
    creator = None
    if row["creator_id"] is not None:
        creator = CreatorSummary(
            id=row["creator_id"],
            handle=row["handle"],
            name=row["creator_name"],
            niches=row["niches"],
            region=row["region"],
        )
    return MeResponse(
        user_id=user_id,
        email=email,
        role=row["role"],
        display_name=row["display_name"],
        brand=brand,
        creator=creator,
    )

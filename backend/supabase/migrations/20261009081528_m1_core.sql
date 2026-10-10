-- M1 core schema: accounts (profiles, brands, products) and the creator
-- marketplace (creators, packages, package_floors), plus creator search.
--
-- Access model (spec §6.3): signed-in users read only rows they own, plus every
-- published package. Nothing is written through the Data API: the backend writes
-- over its privileged connection (which bypasses RLS) and enforces ownership in code.

create extension if not exists vector with schema extensions;

-- Enums ----------------------------------------------------------------------

create type public.user_role as enum ('brand', 'creator');
create type public.content_type as enum ('short_video', 'long_video', 'story', 'live');
create type public.volume_basis as enum ('per_week', 'per_contract');
create type public.preferred_channel as enum ('email_first', 'phone_ok', 'email_only');
create type public.package_status as enum ('draft', 'published');

-- Tables ---------------------------------------------------------------------

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  role public.user_role not null,
  display_name text not null,
  avatar_url text,
  created_at timestamptz not null default now()
);

create table public.brands (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references public.profiles (id) on delete cascade,
  company_name text not null,
  category text,
  default_pitch text,
  contact_email text
);

create index brands_profile_id_idx on public.brands (profile_id);

create table public.products (
  id uuid primary key default gen_random_uuid(),
  brand_id uuid not null references public.brands (id) on delete cascade,
  name text not null,
  summary text,
  key_claims text[] not null default '{}',
  category text
);

create index products_brand_id_idx on public.products (brand_id);

-- Holds contact details (email, phone), so only the owning creator may read it;
-- brands see creators only through the API, which never returns contact fields.
-- profile_id is null for seeded creators that have no login.
create table public.creators (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid unique references public.profiles (id) on delete cascade,
  handle text not null unique,
  name text not null,
  avatar_url text,
  bio text,
  niches text[] not null default '{}',
  platforms jsonb,
  region text,
  languages text[] not null default '{}',
  followers integer not null default 0 check (followers >= 0),
  engagement_rate numeric check (engagement_rate >= 0),
  email text,
  phone text check (phone ~ '^\+[1-9][0-9]{1,14}$'), -- E.164
  phone_opt_in boolean not null default false,
  contact_opt_out boolean not null default false,
  embedding extensions.vector(768),
  embedding_text_hash text
);

create index creators_embedding_idx on public.creators
  using hnsw (embedding extensions.vector_cosine_ops);

create table public.packages (
  id uuid primary key default gen_random_uuid(),
  creator_id uuid not null references public.creators (id) on delete cascade,
  name text not null,
  content_type public.content_type not null,
  niche text not null,
  volume_count integer not null check (volume_count >= 1),
  volume_basis public.volume_basis not null,
  base_price_cents integer not null check (base_price_cents > 0),
  currency text not null default 'USD' check (currency ~ '^[A-Z]{3}$'),
  included text[] not null default '{}',
  freebies text[] not null default '{}',
  -- [{name, price_cents, unit}] with unit in ('video', 'item')
  addons jsonb not null default '[]' check (jsonb_typeof(addons) = 'array'),
  -- [{name, price_cents}]
  extras jsonb not null default '[]' check (jsonb_typeof(extras) = 'array'),
  slots_per_month integer check (slots_per_month >= 0),
  lead_time_days integer check (lead_time_days >= 0),
  preferred_channel public.preferred_channel not null,
  status public.package_status not null default 'draft',
  updated_at timestamptz not null default now()
);

-- Leads with the foreign key; also serves the "published package" lookups.
create index packages_creator_id_status_idx on public.packages (creator_id, status);

-- The creator's private floor: never copied anywhere else (spec §6.2).
create table public.package_floors (
  package_id uuid primary key references public.packages (id) on delete cascade,
  floor_price_cents integer not null check (floor_price_cents > 0)
);

-- Row-level security -----------------------------------------------------------

alter table public.profiles enable row level security;
alter table public.brands enable row level security;
alter table public.products enable row level security;
alter table public.creators enable row level security;
alter table public.packages enable row level security;
alter table public.package_floors enable row level security;

create policy "Users read their own profile"
  on public.profiles for select to authenticated
  using (id = (select auth.uid()));

create policy "Brand owners read their brands"
  on public.brands for select to authenticated
  using (profile_id = (select auth.uid()));

create policy "Brand owners read their products"
  on public.products for select to authenticated
  using (
    brand_id in (
      select b.id from public.brands b where b.profile_id = (select auth.uid())
    )
  );

create policy "Creators read their own creator row"
  on public.creators for select to authenticated
  using (profile_id = (select auth.uid()));

create policy "Signed-in users read published packages and their own"
  on public.packages for select to authenticated
  using (
    status = 'published'
    or creator_id in (
      select c.id from public.creators c where c.profile_id = (select auth.uid())
    )
  );

create policy "Creators read their own package floors"
  on public.package_floors for select to authenticated
  using (
    package_id in (
      select p.id
      from public.packages p
      join public.creators c on c.id = p.creator_id
      where c.profile_id = (select auth.uid())
    )
  );

-- Data API privileges: anon gets nothing; authenticated may only read (RLS
-- narrows the rows). No write privileges, matching the absence of write policies.
revoke all on table
  public.profiles, public.brands, public.products,
  public.creators, public.packages, public.package_floors
  from anon, authenticated;

grant select on table
  public.profiles, public.brands, public.products,
  public.creators, public.packages, public.package_floors
  to authenticated;

-- Creator search -------------------------------------------------------------

-- Creators with at least one published package that satisfies the price and
-- content-type filters on that same package, then the creator-level filters.
-- A null (or empty) filter is not applied. Ordered by cosine distance to
-- query_embedding when given (creators without an embedding last), otherwise by
-- followers; distance is null when no query_embedding is given.
create function public.match_creators(
  query_embedding extensions.vector(768) default null,
  max_price_cents integer default null,
  content_types text[] default null,
  niches text[] default null,
  region text default null,
  min_followers integer default null,
  match_limit integer default 24
)
returns table (creator_id uuid, distance double precision)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    c.id as creator_id,
    c.embedding operator(extensions.<=>) match_creators.query_embedding as distance
  from public.creators c
  where exists (
      select 1
      from public.packages p
      where p.creator_id = c.id
        and p.status = 'published'
        and (match_creators.max_price_cents is null
             or p.base_price_cents <= match_creators.max_price_cents)
        and (coalesce(cardinality(match_creators.content_types), 0) = 0
             or p.content_type::text = any (match_creators.content_types))
    )
    and (coalesce(cardinality(match_creators.niches), 0) = 0
         or c.niches && match_creators.niches)
    and (match_creators.region is null or c.region = match_creators.region)
    and (match_creators.min_followers is null or c.followers >= match_creators.min_followers)
  order by distance nulls last, c.followers desc, c.id
  limit match_creators.match_limit;
$$;

-- A backend search primitive: under RLS a signed-in caller would see only their
-- own creator row, so clients never call it directly.
revoke execute on function public.match_creators from public, anon, authenticated;

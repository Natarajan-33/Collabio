-- M3: the deal loop. Hire targets and offer expiry, deals with payment milestones, and a
-- transactional outbox for notification email. Same access model: parties read via RLS,
-- only the backend writes.

alter table public.briefs
  add column hires_target integer not null default 1 check (hires_target between 1 and 10);
alter table public.batches
  add column hires_target integer not null default 1 check (hires_target between 1 and 10),
  add column offer_ttl_days integer not null default 7 check (offer_ttl_days between 1 and 30);
alter table public.threads add column expires_at timestamptz;
create index threads_expiry_idx on public.threads (expires_at) where status = 'awaiting_reply';

alter table public.thread_events drop constraint thread_events_type_check;
alter table public.thread_events add constraint thread_events_type_check check (type in (
  'queued', 'email_drafted', 'email_sent', 'email_bounced', 'call_placed', 'call_started',
  'call_offer_logged', 'call_ended', 'email_received', 'counter_submitted', 'brand_counter_sent',
  'accepted', 'declined', 'follow_up_suggested', 'follow_up_approved', 'awarded', 'closed_lost',
  'needs_review', 'failed', 'retried', 'offer_expired'));

create table public.deals (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null unique references public.threads (id) on delete cascade,
  batch_id uuid not null references public.batches (id) on delete cascade,
  brand_id uuid not null references public.brands (id) on delete cascade,
  creator_id uuid not null references public.creators (id) on delete cascade,
  package_id uuid not null references public.packages (id),
  videos integer not null check (videos >= 1),
  format text not null check (format in ('short_video', 'long_video', 'story', 'live')),
  price_cents integer not null check (price_cents >= 1),
  go_live_by date not null,
  conditions text[] not null default '{}',
  addons text[] not null default '{}',
  awarded_event_id bigint not null references public.thread_events (id),
  status text not null default 'booked' check (status in ('booked')),
  created_at timestamptz not null default now()
);
create index deals_brand_idx on public.deals (brand_id, created_at desc);
create index deals_creator_idx on public.deals (creator_id, created_at desc);

create table public.deal_milestones (
  id uuid primary key default gen_random_uuid(),
  deal_id uuid not null references public.deals (id) on delete cascade,
  seq integer not null check (seq >= 1),
  title text not null check (char_length(title) between 1 and 80),
  amount_cents integer not null check (amount_cents >= 100),
  due_date date not null,
  status text not null default 'pending' check (status in ('pending')),
  unique (deal_id, seq)
);

create function public.deals_immutable() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (to_jsonb(new) - 'status') is distinct from (to_jsonb(old) - 'status') then
    raise exception 'deals are immutable except status';
  end if;
  return new;
end $$;
create trigger deals_immutable before update on public.deals
  for each row execute function public.deals_immutable();

create function public.milestones_immutable() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (to_jsonb(new) - 'status') is distinct from (to_jsonb(old) - 'status') then
    raise exception 'milestones are immutable except status';
  end if;
  return new;
end $$;
create trigger milestones_immutable before update on public.deal_milestones
  for each row execute function public.milestones_immutable();

-- At commit, every touched deal must have exactly `videos` milestones summing to its price.
create function public.check_deal_milestones() returns trigger
language plpgsql set search_path = '' as $$
declare
  d_id uuid;
  d record;
  n integer;
  total bigint;
begin
  if tg_table_name = 'deals' then d_id := new.id;
  elsif tg_op = 'DELETE' then d_id := old.deal_id;
  else d_id := new.deal_id;
  end if;
  select videos, price_cents into d from public.deals where id = d_id;
  if not found then return null; end if;  -- deal deleted in the same transaction
  select count(*), coalesce(sum(amount_cents), 0) into n, total
    from public.deal_milestones where deal_id = d_id;
  if n <> d.videos or total <> d.price_cents then
    raise exception 'deal % milestones: % rows summing to %, expected % summing to %',
      d_id, n, total, d.videos, d.price_cents;
  end if;
  return null;
end $$;
create constraint trigger deals_need_milestones after insert on public.deals
  deferrable initially deferred for each row execute function public.check_deal_milestones();
create constraint trigger milestones_match_deal after insert or update or delete on public.deal_milestones
  deferrable initially deferred for each row execute function public.check_deal_milestones();

create table public.outbox_emails (
  id bigserial primary key,
  kind text not null check (kind in (
    'creator_brand_countered', 'creator_awarded', 'creator_closed',
    'brand_creator_countered', 'brand_creator_accepted', 'brand_creator_declined',
    'brand_needs_review')),
  thread_id uuid not null references public.threads (id) on delete cascade,
  event_id bigint not null references public.thread_events (id),
  to_role text not null check (to_role in ('brand', 'creator')),
  payload jsonb not null default '{}' check (jsonb_typeof(payload) = 'object'),
  status text not null default 'pending' check (status in ('pending', 'sent', 'failed', 'skipped')),
  attempts integer not null default 0,
  next_attempt_at timestamptz not null default now(),
  last_error text,
  resend_id text,
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  unique (kind, event_id)
);
create index outbox_pending_idx on public.outbox_emails (next_attempt_at) where status = 'pending';

alter table public.deals enable row level security;
alter table public.deal_milestones enable row level security;
alter table public.outbox_emails enable row level security;  -- no policies: backend only

create policy "Deal parties read their deals" on public.deals for select to authenticated
  using (
    brand_id in (select b.id from public.brands b where b.profile_id = (select auth.uid()))
    or creator_id in (select c.id from public.creators c where c.profile_id = (select auth.uid()))
  );
create policy "Deal parties read their milestones" on public.deal_milestones for select to authenticated
  using (deal_id in (select d.id from public.deals d));  -- deals' own policy filters the subquery

-- Supabase grants new public tables to anon and authenticated by default; as in M1/M2, take
-- that away and give the deal parties SELECT only. The outbox has no client access at all.
revoke all on table public.deals, public.deal_milestones, public.outbox_emails
  from anon, authenticated;
grant select on table public.deals, public.deal_milestones to authenticated;

-- Creator search with an optional "registered creators only" filter. Same body as M1 plus
-- the trailing `registered_only` parameter (default false, so existing callers are unchanged).
drop function public.match_creators(extensions.vector, integer, text[], text[], text, integer, integer);
create function public.match_creators(
  query_embedding extensions.vector(768) default null,
  max_price_cents integer default null,
  content_types text[] default null,
  niches text[] default null,
  region text default null,
  min_followers integer default null,
  match_limit integer default 24,
  registered_only boolean default false
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
    and (not match_creators.registered_only or c.profile_id is not null)
  order by distance nulls last, c.followers desc, c.id
  limit match_creators.match_limit;
$$;

-- A backend search primitive (as in M1): clients never call it directly.
revoke execute on function public.match_creators from public, anon, authenticated;

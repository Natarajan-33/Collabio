-- M2: briefs, batches, negotiation threads with their append-only event log, and
-- transcripts. Same access model as M1: parties read through RLS; only the backend writes.

create function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create function public.reject_event_update() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'thread_events is append-only';
end;
$$;

create table public.briefs (
  id uuid primary key default gen_random_uuid(),
  brand_id uuid not null references public.brands (id) on delete cascade,
  product_id uuid references public.products (id) on delete set null,
  status text not null default 'draft' check (status in ('draft', 'ready', 'launched')),
  brand_name text,
  product_name text,
  product_summary text check (char_length(product_summary) <= 200),
  deliverables_count integer check (deliverables_count >= 1),
  deliverables_format public.content_type,
  deliverable_length_s integer check (deliverable_length_s > 0),
  go_live_by date,
  budget_ceiling_cents integer check (budget_ceiling_cents > 0), -- brand-only (spec §6.2)
  ask_price_cents integer check (ask_price_cents > 0),
  negotiation_ask text,
  flexibility text[] not null default '{}'
    check (flexibility <@ array['timeline', 'price', 'deliverables', 'none']::text[]),
  flexibility_note text,
  contact_email text,
  approved_at timestamptz,
  intake_conversation_id text,
  creator_ids uuid[] not null default '{}' check (cardinality(creator_ids) <= 10),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index briefs_brand_id_idx on public.briefs (brand_id);
create trigger briefs_touch before update on public.briefs
  for each row execute function public.touch_updated_at();

create table public.batches (
  id uuid primary key default gen_random_uuid(),
  brief_id uuid not null unique references public.briefs (id) on delete cascade,
  brand_id uuid not null references public.brands (id) on delete cascade,
  launched_at timestamptz not null default now(),
  follow_up_policy text not null default 'off' check (follow_up_policy in ('off', 'suggest', 'auto')),
  follow_up_after interval not null default interval '3 days',
  max_concurrency integer not null default 5 check (max_concurrency between 1 and 10),
  brief_embedding extensions.vector(768)
);
create index batches_brand_id_idx on public.batches (brand_id, launched_at desc);

create table public.threads (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.batches (id) on delete cascade,
  brand_id uuid not null references public.brands (id) on delete cascade,
  creator_id uuid not null references public.creators (id) on delete cascade,
  package_id uuid not null references public.packages (id),
  channel_plan text not null check (channel_plan in ('email', 'call', 'email_then_call')),
  status text not null default 'queued' check (status in (
    'queued', 'drafting', 'awaiting_reply', 'calling', 'in_call', 'countered', 'accepted',
    'declined', 'needs_review', 'failed',
    'awarded', 'closed_lost', 'no_response', 'follow_up_suggested')),
  latest_terms jsonb,
  latest_terms_source text check (latest_terms_source in ('brand', 'creator')),
  reply_token text not null unique,
  call_conversation_id text unique,
  concessions integer not null default 0 check (concessions >= 0),
  next_action_at timestamptz,
  attempts integer not null default 0 check (attempts >= 0),
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (batch_id, creator_id)
);
create index threads_queued_idx on public.threads (created_at) where status = 'queued';
create index threads_live_call_idx on public.threads (status) where status in ('calling', 'in_call');
create index threads_creator_id_idx on public.threads (creator_id);
create trigger threads_touch before update on public.threads
  for each row execute function public.touch_updated_at();

create table public.transcripts (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid references public.threads (id) on delete cascade,
  brief_id uuid references public.briefs (id) on delete cascade,
  kind text not null check (kind in ('email_out', 'email_in', 'call', 'intake')),
  external_id text,
  subject text,
  body_text text,
  turns jsonb not null default '[]' check (jsonb_typeof(turns) = 'array'), -- [{role, text, t}]
  summary text,
  created_at timestamptz not null default now(),
  unique (kind, external_id),
  check (thread_id is not null or brief_id is not null)
);
create index transcripts_thread_id_idx on public.transcripts (thread_id);
create index transcripts_brief_id_idx on public.transcripts (brief_id);

create table public.thread_events (
  id bigserial primary key,
  thread_id uuid not null references public.threads (id) on delete cascade,
  batch_id uuid not null references public.batches (id) on delete cascade,
  brand_id uuid not null references public.brands (id) on delete cascade,
  creator_id uuid not null references public.creators (id) on delete cascade,
  type text not null check (type in (
    'queued', 'email_drafted', 'email_sent', 'email_bounced', 'call_placed', 'call_started',
    'call_offer_logged', 'call_ended', 'email_received', 'counter_submitted',
    'brand_counter_sent', 'accepted', 'declined', 'follow_up_suggested', 'follow_up_approved',
    'awarded', 'closed_lost', 'needs_review', 'failed', 'retried')),
  actor text not null check (actor in ('brand', 'brand_agent', 'creator', 'system')),
  payload jsonb not null default '{}' check (jsonb_typeof(payload) = 'object'),
  terms jsonb,
  transcript_id uuid references public.transcripts (id) on delete set null,
  external_id text,
  created_at timestamptz not null default now(),
  unique (type, external_id)
);
create index thread_events_thread_id_idx on public.thread_events (thread_id, id);
create index thread_events_batch_id_idx on public.thread_events (batch_id, id);
create trigger thread_events_append_only before update on public.thread_events
  for each row execute function public.reject_event_update();

-- Row-level security ------------------------------------------------------------

alter table public.briefs enable row level security;
alter table public.batches enable row level security;
alter table public.threads enable row level security;
alter table public.transcripts enable row level security;
alter table public.thread_events enable row level security;

create policy "Brand owners read their briefs"
  on public.briefs for select to authenticated
  using (brand_id in (select b.id from public.brands b where b.profile_id = (select auth.uid())));

create policy "Brand owners read their batches"
  on public.batches for select to authenticated
  using (brand_id in (select b.id from public.brands b where b.profile_id = (select auth.uid())));

create policy "Thread parties read their threads"
  on public.threads for select to authenticated
  using (
    brand_id in (select b.id from public.brands b where b.profile_id = (select auth.uid()))
    or creator_id in (select c.id from public.creators c where c.profile_id = (select auth.uid()))
  );

create policy "Thread parties read their thread events"
  on public.thread_events for select to authenticated
  using (
    brand_id in (select b.id from public.brands b where b.profile_id = (select auth.uid()))
    or creator_id in (select c.id from public.creators c where c.profile_id = (select auth.uid()))
  );

create policy "Thread parties read thread transcripts; brands read intake transcripts"
  on public.transcripts for select to authenticated
  using (
    thread_id in (
      select t.id from public.threads t
      where t.brand_id in (select b.id from public.brands b where b.profile_id = (select auth.uid()))
         or t.creator_id in (select c.id from public.creators c where c.profile_id = (select auth.uid()))
    )
    or brief_id in (
      select br.id from public.briefs br
      where br.brand_id in (select b.id from public.brands b where b.profile_id = (select auth.uid()))
    )
  );

revoke all on table
  public.briefs, public.batches, public.threads, public.transcripts, public.thread_events
  from anon, authenticated;
grant select on table
  public.briefs, public.batches, public.threads, public.transcripts, public.thread_events
  to authenticated;

-- The board's doorbell: Realtime delivers thread_events inserts, filtered by RLS.
alter publication supabase_realtime add table public.thread_events;

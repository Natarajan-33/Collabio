-- M4: money. Funding through PayPal Checkout, bonus terms, proof submissions, the Claude
-- settlement runs, PayPal payouts, an append-only money ledger and demo usage caps.
-- Same access model as M3: deal parties read via RLS, only the backend writes.

alter table public.deals drop constraint deals_status_check;
alter table public.deals add constraint deals_status_check
  check (status in ('booked', 'funded', 'completed'));

alter table public.deal_milestones drop constraint deal_milestones_status_check;
alter table public.deal_milestones add constraint deal_milestones_status_check
  check (status in ('pending', 'funded', 'submitted', 'needs_changes', 'verified', 'paid'));

alter table public.brands
  add column auto_approve_limit_cents integer not null default 30000
    check (auto_approve_limit_cents between 0 and 1000000);
alter table public.creators add column payout_email text;

create table public.deal_bonus_terms (
  deal_id uuid primary key references public.deals (id) on delete cascade,
  source_text text not null default '',
  terms jsonb not null check (jsonb_typeof(terms) = 'object'),
  max_bonus_per_video_cents integer not null check (max_bonus_per_video_cents >= 0),
  created_at timestamptz not null default now()
);

create table public.deal_funding (
  deal_id uuid primary key references public.deals (id) on delete cascade,
  paypal_order_id text unique,
  capture_id text unique,
  amount_cents integer not null check (amount_cents >= 1),
  status text not null default 'created' check (status in ('created', 'captured', 'failed')),
  refunded_cents integer not null default 0 check (refunded_cents >= 0),
  captured_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.milestone_submissions (
  id uuid primary key default gen_random_uuid(),
  milestone_id uuid not null references public.deal_milestones (id) on delete cascade,
  post_url text not null,
  caption text not null default '',
  claimed_views integer not null check (claimed_views >= 0),
  screenshot_path text not null,
  status text not null default 'submitted'
    check (status in ('submitted', 'verified', 'needs_changes', 'failed')),
  brief_ok boolean,
  disclosure_ok boolean,
  missing_points text[] not null default '{}',
  views integer check (views >= 0),
  view_confidence text check (view_confidence in ('high', 'medium', 'low')),
  agent_summary text,
  created_at timestamptz not null default now()
);
create index milestone_submissions_milestone_idx on public.milestone_submissions (milestone_id);

create table public.settlement_runs (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid not null unique references public.milestone_submissions (id) on delete cascade,
  status text not null default 'running' check (status in ('running', 'done', 'error')),
  transcript jsonb not null default '[]',
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table public.payouts (
  id uuid primary key default gen_random_uuid(),
  milestone_id uuid not null references public.deal_milestones (id) on delete cascade,
  submission_id uuid references public.milestone_submissions (id) on delete set null,
  amount_cents integer not null check (amount_cents >= 1),
  breakdown jsonb not null default '{}',
  status text not null
    check (status in ('awaiting_approval', 'approved', 'sent', 'success', 'failed', 'rejected')),
  paypal_batch_id text,
  paypal_item_id text,
  sender_batch_id text not null unique,
  decided_by uuid,
  reject_reason text,
  last_error jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index payouts_milestone_idx on public.payouts (milestone_id);
create index payouts_sent_idx on public.payouts (updated_at) where status = 'sent';

create table public.money_events (
  id bigserial primary key,
  deal_id uuid not null references public.deals (id) on delete cascade,
  kind text not null check (kind in (
    'funded', 'payout_queued', 'payout_sent', 'payout_succeeded', 'payout_failed',
    'payout_rejected', 'refunded')),
  amount_cents integer not null default 0,
  paypal_ref text,
  payload jsonb not null default '{}' check (jsonb_typeof(payload) = 'object'),
  created_at timestamptz not null default now()
);
create index money_events_deal_idx on public.money_events (deal_id, id);

create function public.money_events_append_only() returns trigger
language plpgsql set search_path = '' as $$
begin
  if coalesce(current_setting('collabio.demo_reset', true), '') = 'on' then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  raise exception 'money_events is append-only';
end $$;
create trigger money_events_append_only before update or delete on public.money_events
  for each row execute function public.money_events_append_only();

create table public.usage_counters (
  user_id uuid not null,
  day date not null,
  kind text not null,
  count integer not null default 0,
  primary key (user_id, day, kind)
);

alter table public.deal_bonus_terms enable row level security;
alter table public.deal_funding enable row level security;
alter table public.milestone_submissions enable row level security;
alter table public.settlement_runs enable row level security;
alter table public.payouts enable row level security;
alter table public.money_events enable row level security;
alter table public.usage_counters enable row level security;  -- no policies: backend only

-- deals' own RLS policy filters each subquery to the reader's deals.
create policy "Deal parties read bonus terms" on public.deal_bonus_terms for select to authenticated
  using (deal_id in (select d.id from public.deals d));
create policy "Deal parties read funding" on public.deal_funding for select to authenticated
  using (deal_id in (select d.id from public.deals d));
create policy "Deal parties read money events" on public.money_events for select to authenticated
  using (deal_id in (select d.id from public.deals d));
create policy "Deal parties read submissions" on public.milestone_submissions for select
  to authenticated using (milestone_id in (select m.id from public.deal_milestones m));
create policy "Deal parties read payouts" on public.payouts for select to authenticated
  using (milestone_id in (select m.id from public.deal_milestones m));
create policy "Deal parties read settlement runs" on public.settlement_runs for select
  to authenticated
  using (submission_id in (select s.id from public.milestone_submissions s));

revoke all on table public.deal_bonus_terms, public.deal_funding, public.milestone_submissions,
  public.settlement_runs, public.payouts, public.money_events, public.usage_counters
  from anon, authenticated;
grant select on table public.deal_bonus_terms, public.deal_funding, public.milestone_submissions,
  public.settlement_runs, public.payouts, public.money_events to authenticated;

-- Realtime: clients refetch the money view when these change.
alter publication supabase_realtime add table public.payouts, public.milestone_submissions,
  public.money_events, public.deal_funding;

-- Private bucket for proof screenshots; only the backend (secret key) reads and writes.
insert into storage.buckets (id, name, public) values ('proofs', 'proofs', false)
  on conflict (id) do nothing;

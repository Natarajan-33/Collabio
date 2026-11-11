-- money_events stays append-only, but a ledger row may go when its deal is deleted (a test
-- brief torn down, a demo deal re-seeded): by then the deal row is already gone.
create or replace function public.money_events_append_only() returns trigger
language plpgsql set search_path = '' as $$
begin
  if coalesce(current_setting('collabio.demo_reset', true), '') = 'on' then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if tg_op = 'DELETE' and not exists (select 1 from public.deals where id = old.deal_id) then
    return old;
  end if;
  raise exception 'money_events is append-only';
end $$;

-- M3 final review fixes: keep the unstripped inbound email, and give already-open offers an expiry.
-- Additive only.

-- The text of a creator's email reply before quoted history and signature are cut (the
-- brand can expand it in the resolve dialog). Null for every other transcript kind.
alter table public.transcripts add column raw_text text;

-- Threads that entered `awaiting_reply` before offer expiry existed have no deadline, so the
-- expiry worker would never close them. Give them the batch's offer window from now.
update public.threads t
set expires_at = now() + make_interval(days => b.offer_ttl_days)
from public.batches b
where b.id = t.batch_id
  and t.status = 'awaiting_reply'
  and t.expires_at is null;

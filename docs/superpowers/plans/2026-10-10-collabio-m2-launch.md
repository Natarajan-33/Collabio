# Collabio M2 — Brief → Parallel Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A brand turns its Review selection into a complete brief by talking to an agent (or by clicking), launches to up to 10 creators in one click, and watches a live board while personalized emails go out and an AI agent phones a creator, checks every counter against the private budget, and logs offers mid-call. Each call ends with a stored transcript and structured terms.

**Architecture:** The backend gains a pure domain core (delta, brief rules, thread state machine, guardrails, ranking) and an append-only `thread_events` log. Every status change is a conditional update in the same transaction as its event. In-process asyncio workers (orchestrator + call watcher) started in the FastAPI lifespan claim queued threads with `FOR UPDATE SKIP LOCKED` and drive email (Gemini draft → Jinja → Resend) and phone (ElevenLabs outbound call → server tools → post-call webhook or watcher → Gemini structurer). The frontend adds a Brief page that hosts the ElevenLabs brief agent over WebRTC, and a Board page that treats Supabase Realtime inserts on `thread_events` as a doorbell to refetch a server-computed view model.

**Tech Stack (additions to M1):** Jinja2 (new backend dependency) · Resend REST API over `httpx` · ElevenLabs Agents (`AsyncElevenLabs` SDK for calls/tokens/conversations; REST for agent sync) · `@elevenlabs/react` `ConversationProvider`/`useConversation` (WebRTC) · Supabase Realtime `postgres_changes` · GSAP Flip.

**Spec:** `docs/superpowers/specs/2026-10-09-collabio-design.md`. M2 row of §2; §3 steps 2–4; §4.2; §5.1 (board intents), §5.2, §5.4; §6.1–6.4; §7.1–7.5; §8.1; §8.2 (phone-call row); §9 Briefs, Board (list/detail/retry) and ElevenLabs webhook rows; §10 Brief and Board; §11; §12; §13. Read the spec section a task names before starting it.

**Prior art:** `docs/superpowers/plans/2026-10-09-collabio-m1-foundation.md` (conventions, fixtures, rulings) and `docs/superpowers/plans/2026-10-10-m1-followups.md`.

---

## Executing this plan with Cursor (read once)

1. Work on branch `collabio-m2`. It already exists and holds the voice/discover fix commit `2c7f04b`. Do the tasks **in order**, one at a time, and finish each with its commit step before starting the next.
2. Each task lists **Interfaces**. Use those exact names, signatures and field names. Later tasks depend on them, and a renamed function breaks a later task silently.
3. Test steps give test names and the assertions that matter. Write them first, run them, and **watch them fail** before writing code. Never loosen an assertion to make a test pass: fix the code, or stop and flag the conflict.
4. When a step gives a code block, it is a decision (SQL, an algorithm, exact copy), so reproduce it faithfully. When a step gives only a signature, write the body yourself in the style of the surrounding M1 code.
5. Windows shell: put every command on its own line (PowerShell 5.1 has no `&&`). Run Python **only** as `uv run …` from `backend/`. Run npm from `frontend/`.
6. After each task, run the whole suite for the side you touched (`uv run pytest -q` in `backend/`; `npm run typecheck`, `npm run lint` and `npm test` in `frontend/`). It must be green before you commit.
7. Tasks 11–14 and 22 need real accounts (ElevenLabs, Resend, a public tunnel). Code and tests use fakes and run without them. Live verification happens in Task 22, which the human runs.

---

## Scope

**In M2:** briefs (create from the Review selection, get, patch, preview, voice session, launch); the brief agent in the browser; per-creator delta preview and channel plan; the launch orchestrator; personalized outreach email with unsubscribe; AI phone calls with the `check_counter`/`log_offer` server tools; the call watcher; the post-call webhook; the call structurer; the live board with KPI strip, Best-value ranking and Retry; the thread drawer with timeline, transcript and delta; board voice intents (`open_thread`, `sort`); agents-as-code with a sync script.

**Not in M2 (later milestones; do not build):**
- M3: email-reply parsing (Resend inbound webhook), creator Offers board and offer desk, creator counter / accept / decline, brand counter, award, polite declines, **Take call in browser / Join call** (it needs the M3 offer desk).
- M4: follow-up sweep and calls (M2 only stores `follow_up_policy`), analytics, landing page, preflight, demo reset, deployment to Vercel/Fly.

---

## Global Constraints

- Everything in M1's Global Constraints still holds. In particular: money is integer cents, USD only; display as `$1,000` / `$999.50` via `format_cents` / `formatCents`. Use the niche, content-type and channel vocabularies exactly. The Gemini text model is `settings.gemini_text_model` with structured output via `generate_structured`. Ports are 8000 (backend) and 3000 (frontend).
- Next.js 16: before writing Next code, read the relevant guide in `frontend/node_modules/next/dist/docs/` (per `AGENTS.md`). The new pages are Client Components (`"use client"`) and read route params with `useParams()`.
- **Private limits (spec §6.2), the rule that must never break:** the brand's `budget_ceiling_cents` is read only by the briefs service (brand endpoints), `guardrails.check_counter`, and `ranking.rank_threads`. It never appears in `threads`, `thread_events.payload`/`terms`, `transcripts`, an email subject or body, agent dynamic variables for the **negotiation** agent, the outreach or structurer prompts, any creator-readable row, or a log line. The creator's `floor_price_cents` is untouched in M2 and never read. A creator's `email` and `phone` never appear in a brand-facing response or in a `thread_events` payload.
- `thread_events` is append-only. App code never UPDATEs or DELETEs it; a trigger rejects UPDATE. Every thread status change goes through `app.modules.threads.repo.transition` / `apply_event`, in the same transaction as its event.
- Webhook and tool idempotency: `unique (type, external_id)` on `thread_events` and `unique (kind, external_id)` on `transcripts`. A duplicate is skipped silently, never treated as an error.
- Per-thread isolation: an exception while processing one thread records a `failed` event with a human-readable `reason` on that thread and never stops the worker or the other threads.
- **Shared database:** backend tests and the dev backend use the same hosted Supabase project. While running `pytest`, run the dev backend with `WORKERS_ENABLED=0` (or stop it); otherwise its workers can pick up test threads and send real email or place a real call. Fixtures launch with `hold=True` (Task 8), and any API launch test uses only fictional creators.
- Outreach never sends to a reserved address (`example.com/.net/.org`, `*.example`, `*.test`, `*.invalid`, `*.localhost`). All 38 fictional seeded creators use `@example.com`. Their threads record `email_sent` with `{"delivered": false}` and make no Resend call.
- Calls go only to creators with `phone_opt_in = true` and a phone. Phone calls are never retried automatically (only a Retry click retries them). There are at most 20 calls per brand per UTC day. The negotiation agent's call is capped at 300 s.
- AI disclosure copy (exact). Call first message: `Hi {{creator_first_name}}, this is an AI assistant calling on behalf of {{brand_name}}. This call is recorded for both parties' records — is now a good time?` Email footer: `This email was written with AI assistance on behalf of {brand_name}.`
- Thread statuses (exact strings): `queued`, `drafting`, `awaiting_reply`, `calling`, `in_call`, `countered`, `accepted`, `declined`, `needs_review`, `failed`. The DB check constraint also reserves `awarded`, `closed_lost`, `no_response` and `follow_up_suggested` for M3/M4.
- Thread event types (exact, spec §6.1): `queued`, `email_drafted`, `email_sent`, `email_bounced`, `call_placed`, `call_started`, `call_offer_logged`, `call_ended`, `email_received`, `counter_submitted`, `brand_counter_sent`, `accepted`, `declined`, `follow_up_suggested`, `follow_up_approved`, `awarded`, `closed_lost`, `needs_review`, `failed`, `retried`. M2 writes only `queued`, `email_drafted`, `email_sent`, `call_placed`, `call_started`, `call_offer_logged`, `call_ended`, `needs_review`, `failed` and `retried`.
- "Today" is the UTC date, `datetime.now(UTC).date()`. Pure functions take `today: date` as a parameter and never read the clock.
- ElevenLabs agents: LLM `gemini-3.5-flash`, TTS model `eleven_flash_v2`, language `en`. The two agents have distinct voices.
- Backend env added in M2 (`backend/.env.example`): `ELEVENLABS_BRIEF_AGENT_ID`, `ELEVENLABS_NEGOTIATION_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID`, `ELEVENLABS_WEBHOOK_SECRET`, `ELEVENLABS_TOOL_SECRET`, `RESEND_API_KEY`, `RESEND_FROM`, `RESEND_INBOUND_DOMAIN`, `PUBLIC_BACKEND_URL`, `PUBLIC_FRONTEND_URL`, `WORKERS_ENABLED`. The agent sync script also reads `ELEVENLABS_BRIEF_VOICE_ID` and `ELEVENLABS_NEGOTIATION_VOICE_ID`, which the app never reads.
- Frontend: every price, count and duration uses the `num` utility (tabular mono). Motion only signals a state change, and every animation honours `prefers-reduced-motion`. Missing fields reuse the existing `voice-missing` utility.
- Commits: conventional style as in M1, e.g. `feat(briefs): …` or `fix(board): …`, with one commit per task. No co-author trailer is required.

## Rulings (where the spec is silent, or this plan deliberately narrows it)

1. **No separate `sent` status.** `email_sent` moves a thread straight from `drafting` to `awaiting_reply`, because nothing happens between the two. The board labels `awaiting_reply` as "Sent".
2. **Status-like columns are `text` + `CHECK`, not enums.** M3/M4 can then extend them by dropping and re-adding a constraint.
3. **Extra columns** `threads.call_conversation_id` (watcher lookup, unique) and `threads.concessions` (count of over-budget verdicts given on the thread). Neither is private. `batches.brief_embedding` feeds audience fit (Ruling 8).
4. **`check_counter` results are never stored.** A suggested counter reveals the ceiling (the first concession is the midpoint of ask and ceiling). Transcript turns keep only `{role, text, t}`, so tool calls and tool results are dropped before storage.
5. **Server tools accept a thread in `calling` or `in_call`.** The watcher polls every 2 s and can lag the agent's first tool call.
6. **Two doors to call completion.** The post-call webhook and the call watcher (which fetches the finished conversation) both call `complete_call`, made idempotent by the unique keys. The webhook speeds completion up but is not required. The server tools still need a public URL.
7. **Reserved-domain recipients** get no Resend call: `email_sent` is recorded with `{"delivered": false}`, and the card says "Not delivered: test address".
8. **Audience fit** = mean of the available normalized components among the eligible threads: semantic similarity (creator embedding vs a brief embedding made at launch; skipped if Gemini fails) and engagement rate.
9. **Agents speak dollars.** Tool parameters are USD amounts. The backend (server tools) and the browser (client tools) convert them to cents.
10. **One microphone.** While the brief agent conversation is live, the Voice Dock is paused and shows why.
11. **The email's "Review & respond in Collabio" link** targets `/creator/offers/{threadId}` as the spec says. That page arrives in M3; until then it lands on the creator app's not-found page.
12. **Follow-up policy** is chosen on the brief and stored on the batch. Nothing acts on it until M4.
13. **Unsubscribe** is `GET`/`POST {PUBLIC_BACKEND_URL}/api/v1/unsubscribe/{reply_token}` (no auth). It sets `creators.contact_opt_out = true` and is also sent as `List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers.
14. **Transports.** Resend goes over `httpx` (its Python SDK is synchronous). ElevenLabs runtime calls go through the existing `AsyncElevenLabs` SDK. The agent sync script talks REST over `httpx`, so the JSON under `backend/agents/` is exactly what is sent.
15. **`threads.attempts` counts Retry clicks, not worker claims.** The Resend idempotency key `thread:{id}:email:{attempts}` is therefore stable across a restart, and the stored draft is reused for the same attempt.
16. **`email_then_call` behaves as `email` in M2.** The call step is a follow-up, which is M4.

## Review Focus

1. **The ceiling leaks into creator-visible data.** Possible paths: a stored `check_counter` result, tool results inside a transcript, the email body, the negotiation agent's variables, the structurer summary. Expected: the ceiling (raw cents or formatted dollars) appears nowhere a creator can read. Tests: Task 9 `test_email_and_prompt_never_mention_ceiling`, Task 11 `test_dynamic_variables_exclude_ceiling`, Task 12 `test_check_counter_result_not_stored`, Task 13 `test_ceiling_never_stored_after_full_call`.
2. **Duplicate deliveries:** the webhook retried, Launch double-clicked, two tabs launching. Expected: exactly one batch, one `call_ended` and one Gemini structurer call. Tests: Task 8 `test_concurrent_launch_creates_one_batch`, Task 13 `test_duplicate_post_call_is_one_event`.
3. **Backend restarts mid-launch** (killed between the Resend send and recording it). Expected: each creator gets one email, and a call that was never placed is marked failed rather than re-dialed. Tests: Task 10 `test_restart_mid_launch_sends_each_email_once`, `test_stuck_call_is_failed_not_redialed`.
4. **Nobody answers the phone.** Expected: the card shows "Failed · No answer" with Retry within seconds of the call ending, not an endless "Calling…". Test: Task 11 `test_unanswered_call_fails_with_retry`.
5. **The agent hands a tool value in an odd shape** ("1,200", "$1,200", "twelve hundred", "next Friday"). Expected: digit forms are accepted and converted to cents; words get an error the agent can re-ask from, and nothing invalid is stored. Tests: Task 19 `agentFieldToPatch` table; Task 12 `test_log_offer_ignores_unparseable_date`.

---

## File Structure

```
backend/
  pyproject.toml                         + jinja2
  .env.example                           + M2 variables
  app/config.py                          + M2 settings
  app/main.py                            routers + start/stop workers in lifespan
  app/api/deps.py                        + get_email, require_tool_secret
  app/api/routers/briefs.py              briefs CRUD, preview, voice-session, launch
  app/api/routers/board.py               batches list/detail, thread detail, retry
  app/api/routers/webhooks.py            ElevenLabs tools + post-call
  app/api/routers/unsubscribe.py         unsubscribe by reply token
  app/core/delta.py                      listed price, anchor package, headline, PackageDelta
  app/core/brief_rules.py                field errors, missing fields, violations
  app/core/thread_state.py               statuses, transitions, status after a call
  app/core/guardrails.py                 check_counter, channel policy, call cap
  app/core/ranking.py                    best-value ranking
  app/core/reply_token.py                reply tokens and reply-to address
  app/core/contact.py                    reserved addresses, first names
  app/core/signatures.py                 ElevenLabs webhook HMAC
  app/schemas/negotiation.py             NegotiationTerms, PackageDelta, event/actor types, tool bodies
  app/schemas/briefs.py                  brief fields, requests, responses
  app/schemas/board.py                   BestValue, cards, batch/thread view models
  app/adapters/elevenlabs.py             + conversation token, outbound call, conversation snapshot
  app/adapters/email.py                  Resend client
  app/modules/threads/repo.py            event log, transitions, claims, live calls
  app/modules/briefs/{repo,service,launch,voice_session}.py
  app/modules/outreach/{prompts,render,service}.py
  app/modules/negotiation/{calls,tools,prompts,structurer,completion}.py
  app/modules/board/{repo,service}.py
  app/workers/{__init__,orchestrator,call_watcher,sweep,runtime}.py
  templates/email/outreach.html.j2, outreach.txt.j2
  agents/brief_agent.json, agents/negotiation_agent.json, agents/tools/*.json
  scripts/sync_agents.py
  supabase/migrations/20261010120000_m2_negotiation.sql
  tests/... (named per task)
frontend/
  lib/api/openapi.json, lib/api/schema.d.ts   regenerated
  components/shell/app-shell.tsx              + Board nav
  components/voice/voice-screen.tsx           + pause
  components/voice/voice-dock.tsx             honours pause
  app/brand/discover/review/page.tsx          Start negotiation creates a brief
  lib/supabase/realtime.ts                    useBatchDoorbell
  lib/brief/{state,agent-tools}.ts
  components/brief/{brief-card,field-editor,creators-panel,launch-bar,agent-session}.tsx
  app/brand/briefs/[id]/page.tsx
  lib/board/state.ts
  components/board/{status-pill,kpi-strip,thread-card,email-reveal,thread-drawer,timeline,transcript-view,delta-table}.tsx
  app/brand/batches/page.tsx, app/brand/batches/[id]/page.tsx
  tests/unit/*.test.ts(x), tests/e2e/m2.spec.ts
```

---

### Task 1: M2 settings, schema, row-level security and realtime

**Files:**
- Modify: `backend/app/config.py`, `backend/.env.example`
- Create: `backend/supabase/migrations/20261010120000_m2_negotiation.sql`
- Modify: `backend/tests/db/conftest.py` (Factory gains `brief`, `batch`, `thread`, `event`)
- Test: `backend/tests/core/test_config.py` (extend), `backend/tests/db/test_rls_m2.py`, `backend/tests/db/test_m2_schema.py`

**Interfaces:**
- Produces settings fields (defaults in parentheses): `elevenlabs_brief_agent_id` (""), `elevenlabs_negotiation_agent_id` (""), `elevenlabs_phone_number_id` (""), `elevenlabs_webhook_secret` ("", `repr=False`), `elevenlabs_tool_secret` ("", `repr=False`), `resend_api_key` ("", `repr=False`), `resend_from` (""), `resend_inbound_domain` (""), `public_backend_url` ("http://localhost:8000"), `public_frontend_url` ("http://localhost:3000"), `workers_enabled` (True).
- Produces tables `briefs`, `batches`, `threads`, `transcripts`, `thread_events` exactly as below.
- Produces `Factory.brief(brand: Brand, **cols) -> uuid.UUID`, `Factory.batch(brief_id, brand: Brand) -> uuid.UUID`, `Factory.thread(batch_id, brand: Brand, creator: Creator, package_id, *, status="queued", channel_plan="email") -> uuid.UUID` (random `reply_token`), `Factory.event(thread_id, type, *, actor="system", payload=None, external_id=None) -> int`. Factory resolves `batch_id`, `brand_id` and `creator_id` from the thread.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_config.py`: `test_m2_settings_defaults` builds `Settings(_env_file=None)` and asserts every default above. `test_m2_secrets_hidden_from_repr` sets `elevenlabs_tool_secret="s3cret"`, `elevenlabs_webhook_secret="w"` and `resend_api_key="r"`, then asserts none of those values appear in `repr(settings)`.

`tests/db/test_rls_m2.py` (`pytestmark = pytest.mark.db`; use `db_conn`, `as_user`, `factory`):
```python
async def test_creator_cannot_read_briefs_or_batches(db_conn, as_user, factory): ...
    # brand + brief + batch + thread for creator; as the creator: 0 rows from briefs, 0 from batches
async def test_brand_reads_only_its_own_briefs(db_conn, as_user, factory): ...
async def test_thread_parties_read_threads_and_events(db_conn, as_user, factory): ...
    # brand A sees its thread + events; brand B sees none; the thread's creator sees both; another creator sees none
async def test_creator_reads_call_transcript_but_not_intake(db_conn, as_user, factory): ...
    # transcripts(kind='call', thread_id=t) visible to the creator; transcripts(kind='intake', brief_id=b) not
async def test_anon_reads_nothing(db_conn, factory): ...  # set local role anon -> 0 rows from all five tables
```
`tests/db/test_m2_schema.py`:
```python
async def test_thread_events_reject_update(db_conn, factory): ...      # UPDATE raises asyncpg.RaiseError containing "append-only"
async def test_duplicate_event_external_id_rejected(db_conn, factory): ...  # same (type, external_id) twice -> UniqueViolationError
async def test_null_external_ids_never_collide(db_conn, factory): ...   # two 'queued' events, external_id NULL -> both insert
async def test_unknown_status_rejected(db_conn, factory): ...           # status 'sent' -> CheckViolationError
async def test_thread_events_published_for_realtime(db_conn): ...
    # select 1 from pg_publication_tables where pubname='supabase_realtime' and tablename='thread_events'
async def test_updated_at_touched_on_update(db_conn, factory): ...      # update threads status -> updated_at > created_at
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/core/test_config.py tests/db/test_rls_m2.py tests/db/test_m2_schema.py -v`
Expected: the config tests FAIL with missing attributes. The DB tests FAIL because the tables are missing (or SKIP if the database is not configured; run with `REQUIRE_DB=1` to be sure).

- [ ] **Step 3: Add the settings and `.env.example` entries**

Add the fields to `Settings` after `elevenlabs_api_key`, in the order above. In `.env.example`, add each variable with a one-line comment. The URLs say "public HTTPS tunnel or deploy URL; ElevenLabs calls the tool webhooks here".

- [ ] **Step 4: Write the migration**

```sql
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
```

- [ ] **Step 5: Apply the migration to the hosted project**

Follow `backend/README.md` § Database. Run `supabase link --project-ref jilkhalmsumjwfuteolz` once if it is not linked yet, then `supabase db push` from `backend/`. Expected: "Applying migration 20261010120000_m2_negotiation.sql…" and no error. (Pasting the file into the Supabase SQL editor is equivalent.)

- [ ] **Step 6: Extend the Factory, run the tests**

Add the four Factory methods (Interfaces). Run: `REQUIRE_DB=1 uv run pytest tests/core/test_config.py tests/db -v` (PowerShell: `$env:REQUIRE_DB = "1"` on its own line first).
Expected: all pass, including every M1 DB test.

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/.env.example backend/supabase/migrations backend/tests
git commit -m "feat(db): M2 schema for briefs, batches, threads, events and transcripts"
```

---

### Task 2: Negotiation terms and the delta engine

**Files:**
- Create: `backend/app/schemas/negotiation.py`, `backend/app/core/delta.py`
- Test: `backend/tests/core/test_delta.py`

**Interfaces:**
- Consumes: `PackageTerms`, `ContentType` (`app.schemas.packages`), `format_cents`, `extra_video_addon`.
- Produces in `app/schemas/negotiation.py`:
  - `Stance = Literal["offer", "counter", "accept", "decline", "question", "no_commitment"]`
  - `TermsChannel = Literal["call", "email", "in_app"]`
  - `EventType` = Literal of the 20 event types (Global Constraints); `Actor = Literal["brand", "brand_agent", "creator", "system"]`
  - `NegotiationTerms(videos: int | None = Field(None, ge=1), format: ContentType | None = None, price_cents: int | None = Field(None, gt=0), go_live_by: date | None = None, conditions: list[str] = [], addons: list[str] = [], stance: Stance, source: TermsChannel, confidence: float = Field(ge=0, le=1), open_questions: list[str] = [])`
  - `DeltaFlag = Literal["below_base_price", "lead_time_conflict", "estimated"]`
  - `ListedPrice(cents: int, estimated: bool)`
  - `PackageDelta(package_id: UUID, package_name: str, listed_videos: int, ask_videos: int, latest_videos: int | None, listed_price_cents: int, ask_price_cents: int, latest_price_cents: int | None, listed_per_video_cents: int, ask_per_video_cents: int, latest_per_video_cents: int | None, lead_time_days: int | None, days_to_go_live: int, headline: str, latest_headline: str | None, flags: list[DeltaFlag])`. Here `listed_price_cents` is the listed price **for the ask's video count**.
  - `TranscriptTurn(role: Literal["agent", "user"], text: str, t: float)`
- Produces in `app/core/delta.py`:
  - `listed_price_for(pkg: PackageTerms, videos: int) -> ListedPrice` (spec §7.1, exactly).
  - `delta_headline(pkg: PackageTerms, videos: int, price_cents: int) -> str`
  - `pick_anchor_package(packages: Sequence[tuple[UUID, PackageTerms]], *, fmt: ContentType | None, videos: int | None) -> tuple[UUID, PackageTerms]`. Order: same `content_type` as `fmt` first (when `fmt` is given), then smallest `abs(volume_count - videos)` (when `videos` is given), then lowest `base_price_cents`, then `name`. Raises `ValueError` on an empty sequence.
  - `compute_delta(package_id: UUID, pkg: PackageTerms, *, ask_videos: int, ask_price_cents: int, go_live_by: date, today: date, latest: NegotiationTerms | None = None) -> PackageDelta`

- [ ] **Step 1: Write the failing tests**

```python
PKG = PackageTerms(name="Review Pair", content_type="short_video", niche="consumer_tech", volume_count=2,
                   volume_basis="per_contract", base_price_cents=100000, preferred_channel="email_first",
                   addons=[Addon(name="Extra video", price_cents=40000, unit="video")], lead_time_days=10)
NO_ADDON = PKG.model_copy(update={"addons": []})

def test_listed_price_within_volume_is_base(): assert listed_price_for(PKG, 2) == ListedPrice(cents=100000, estimated=False)
def test_listed_price_uses_video_addon(): assert listed_price_for(PKG, 3) == ListedPrice(cents=140000, estimated=False)
def test_listed_price_extrapolates_without_addon(): assert listed_price_for(NO_ADDON, 4) == ListedPrice(cents=200000, estimated=True)
def test_headline_spec_example(): assert delta_headline(PKG, 3, 100000) == "+1 video vs package · $400 under list (−29%)"
def test_headline_at_list(): assert delta_headline(PKG, 2, 100000) == "Same videos as package · At list price"
def test_headline_fewer_videos(): assert delta_headline(PKG.model_copy(update={"volume_count": 3, "base_price_cents": 150000}), 2, 120000) == "−1 video vs package · $300 under list (−20%)"
def test_headline_over_list(): assert delta_headline(PKG, 2, 110000) == "Same videos as package · $100 over list (+10%)"
def test_headline_estimated_suffix(): assert delta_headline(NO_ADDON, 4, 200000) == "+2 videos vs package · At list price · estimated"
def test_flags_below_base_and_lead_time():
    d = compute_delta(PID, PKG, ask_videos=2, ask_price_cents=90000, go_live_by=date(2026, 10, 15), today=date(2026, 10, 10))
    assert d.flags == ["below_base_price", "lead_time_conflict"] and d.days_to_go_live == 5
def test_per_video_rounding():
    d = compute_delta(PID, PKG, ask_videos=3, ask_price_cents=110000, go_live_by=date(2026, 12, 1), today=date(2026, 10, 10))
    assert (d.ask_per_video_cents, d.listed_per_video_cents) == (36667, 46667)
def test_latest_terms_fill_latest_fields():
    latest = NegotiationTerms(videos=3, price_cents=120000, stance="counter", source="call", confidence=0.9)
    d = compute_delta(PID, PKG, ask_videos=3, ask_price_cents=100000, go_live_by=date(2026, 12, 1), today=date(2026, 10, 10), latest=latest)
    assert d.latest_per_video_cents == 40000 and d.latest_headline == "+1 video vs package · $200 under list (−14%)"
def test_anchor_prefers_format_then_volume_then_price(): ...  # three packages; assert the chosen id for (fmt, videos) cases
def test_anchor_empty_raises(): ...
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/core/test_delta.py -v` → FAIL (modules missing).

- [ ] **Step 3: Implement the schema module and `core/delta.py`**

Headline rules (exact):
- Videos part, with `d = videos - pkg.volume_count`: `d > 0` → `+{d} video(s) vs package`; `d < 0` → `−{|d|} video(s) vs package` (U+2212 minus); `d == 0` → `Same videos as package`. Use "video" when `|d| == 1`, else "videos".
- Price part, against `listed = listed_price_for(pkg, videos).cents` and `diff = price_cents - listed`, `pct = round(abs(diff) / listed * 100)`: `diff < 0` → `{format_cents(-diff)} under list (−{pct}%)`; `diff > 0` → `{format_cents(diff)} over list (+{pct}%)`; `0` → `At list price`.
- Join the parts with `" · "`, and append `" · estimated"` when the listed price was estimated.

Per-video values are `round(price / videos)`. `latest_*` fields and `latest_headline` are set only when `latest` has both `videos` and `price_cents`. Flags appear in this order: `below_base_price` (`ask_price_cents < pkg.base_price_cents`), then `lead_time_conflict` (`lead_time_days` is set and `days_to_go_live < lead_time_days`), then `estimated`.

- [ ] **Step 4: Run them**

Run: `uv run pytest tests/core/test_delta.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/negotiation.py backend/app/core/delta.py backend/tests/core/test_delta.py
git commit -m "feat(core): negotiation terms and the package delta engine"
```

---

### Task 3: Brief rules, thread state machine, guardrails

**Files:**
- Create: `backend/app/schemas/briefs.py` (field model and literals only; Task 7 adds the API models), `backend/app/core/brief_rules.py`, `backend/app/core/thread_state.py`, `backend/app/core/guardrails.py`
- Test: `backend/tests/core/test_brief_rules.py`, `backend/tests/core/test_thread_state.py`, `backend/tests/core/test_guardrails.py`

**Interfaces:**
- Produces in `app/schemas/briefs.py`: `Flexibility = Literal["timeline", "price", "deliverables", "none"]`, `ChannelPlan = Literal["email", "call", "email_then_call"]`, `FollowUpPolicy = Literal["off", "suggest", "auto"]`, `BriefStatus = Literal["draft", "ready", "launched"]`, and `BriefFields` (every field optional, `flexibility: list[Flexibility] = []`): `brand_name, product_name, product_summary: str | None; deliverables_count: int | None; deliverables_format: ContentType | None; deliverable_length_s: int | None; go_live_by: date | None; budget_ceiling_cents, ask_price_cents: int | None; negotiation_ask: str | None; flexibility; flexibility_note: str | None; contact_email: str | None`. Also `REQUIRED_BRIEF_FIELDS: tuple[str, ...] = ("brand_name", "product_name", "product_summary", "deliverables_count", "deliverables_format", "go_live_by", "budget_ceiling_cents", "ask_price_cents", "negotiation_ask", "flexibility", "contact_email")`.
- Produces in `app/core/brief_rules.py`:
  - `BRIEF_FIELD_LABELS: dict[str, str]`: brand_name "brand name", product_name "product name", product_summary "product summary", deliverables_count "number of deliverables", deliverables_format "deliverable format", deliverable_length_s "video length", go_live_by "go-live date", budget_ceiling_cents "budget ceiling", ask_price_cents "opening ask", negotiation_ask "what to negotiate for", flexibility "flexibility", flexibility_note "flexibility note", contact_email "contact email".
  - `field_error(field: str, value: object, today: date) -> str | None`. This is the single-field rule used to **reject** a PATCH.
  - `missing_fields(brief: BriefFields) -> list[str]` in `REQUIRED_BRIEF_FIELDS` order. A blank or whitespace-only string counts as missing, and so does an empty `flexibility`.
  - `violations(brief: BriefFields, today: date) -> list[RuleViolation]`: every present field's `field_error`, plus the cross-field rule. Use `RuleViolation` from `app.schemas.packages`.
  - `is_launchable(brief: BriefFields, today: date) -> bool`
- Produces in `app/schemas/negotiation.py` (so response schemas can use it): `ThreadStatus` = Literal of the 14 statuses in the migration.
- Produces in `app/core/thread_state.py` (which imports `ThreadStatus` from the schema):
  - `LIVE_STATUSES = frozenset({"queued", "drafting", "calling", "in_call"})`
  - `TRANSITIONS: dict[str, frozenset[str]]` (below); `class IllegalTransition(Exception)`; `check_transition(current: str, target: str) -> None`
  - `status_for_event(event_type: str) -> ThreadStatus | None`; `CONFIDENCE_FLOOR = 0.6`; `status_after_call(terms: NegotiationTerms | None) -> ThreadStatus`
- Produces in `app/core/guardrails.py`:
  - `MAX_CALLS_PER_BRAND_PER_DAY = 20`
  - `CounterVerdict(verdict: Literal["within", "over"], suggested_counter_price_cents: int | None, talking_point: str)`
  - `check_counter(*, ceiling_cents: int, ask_cents: int, brief_videos: int, offered_price_cents: int, offered_videos: int, concessions_made: int, brand_name: str) -> CounterVerdict`
  - `call_allowed(phone: str | None, phone_opt_in: bool) -> bool`
  - `default_channel(preferred: PreferredChannel, phone: str | None, phone_opt_in: bool) -> ChannelPlan`. Returns `"call"` only when `preferred == "phone_ok"` and `call_allowed(...)`; otherwise `"email"`.
  - `channel_violation(plan: ChannelPlan, *, phone: str | None, phone_opt_in: bool, contact_opt_out: bool) -> str | None`. Returns `"Opted out of contact"` for an opted-out creator; `"No phone opt-in"` when `plan` is `call` or `email_then_call` and `call_allowed` is false; otherwise `None`.

- [ ] **Step 1: Write the failing tests**

`test_brief_rules.py`. Error messages are exact:
```python
TODAY = date(2026, 10, 10)
@pytest.mark.parametrize("field,value,message", [
    ("product_summary", "x" * 201, "Keep the product summary to 200 characters."),
    ("deliverables_count", 0, "Ask for at least one deliverable."),
    ("deliverable_length_s", 0, "The video length must be more than 0 seconds."),
    ("go_live_by", TODAY, "The go-live date must be in the future."),
    ("budget_ceiling_cents", 0, "The budget ceiling must be more than $0."),
    ("ask_price_cents", -5, "The opening ask must be more than $0."),
    ("flexibility", ["none", "price"], "“None” can't be combined with other flexibility."),
    ("contact_email", "not-an-email", "Enter a valid contact email."),
])
def test_field_error(field, value, message): assert field_error(field, value, TODAY) == message
def test_valid_values_have_no_error(): ...  # one valid value per field -> None
def test_missing_in_required_order(): assert missing_fields(BriefFields(brand_name="Lumen", product_name=" ")) == list(REQUIRED_BRIEF_FIELDS[1:])
def test_ask_above_ceiling_is_a_violation():
    v = violations(COMPLETE.model_copy(update={"ask_price_cents": 130000, "budget_ceiling_cents": 120000}), TODAY)
    assert v == [RuleViolation(field="ask_price_cents", message="The opening ask can't be above the budget ceiling.")]
def test_complete_brief_is_launchable(): assert is_launchable(COMPLETE, TODAY)
```
`test_thread_state.py`:
```python
@pytest.mark.parametrize("a,b", [("queued","drafting"),("queued","calling"),("drafting","awaiting_reply"),
    ("drafting","queued"),("calling","in_call"),("calling","countered"),("in_call","needs_review"),("failed","queued")])
def test_allowed(a, b): check_transition(a, b)
@pytest.mark.parametrize("a,b", [("queued","awaiting_reply"),("declined","queued"),("awaiting_reply","queued"),("in_call","calling")])
def test_illegal(a, b): pytest.raises(IllegalTransition, check_transition, a, b)
def test_status_for_event(): assert [status_for_event(t) for t in ("email_sent","call_started","failed","retried","needs_review","email_drafted")] == ["awaiting_reply","in_call","failed","queued","needs_review",None]
@pytest.mark.parametrize("stance,expected", [("counter","countered"),("accept","accepted"),("decline","declined"),
    ("offer","awaiting_reply"),("question","awaiting_reply"),("no_commitment","awaiting_reply")])
def test_status_after_call(stance, expected): ...  # confidence 0.9
def test_low_confidence_needs_review(): assert status_after_call(T.model_copy(update={"confidence": 0.59})) == "needs_review"
def test_no_terms_needs_review(): assert status_after_call(None) == "needs_review"
```
`test_guardrails.py`. These are the demo numbers from spec §3:
```python
KW = dict(ceiling_cents=120000, ask_cents=100000, brief_videos=3, brand_name="Lumen Audio")
def test_over_ceiling_first_concession_is_midpoint():
    v = check_counter(offered_price_cents=130000, offered_videos=3, concessions_made=0, **KW)
    assert (v.verdict, v.suggested_counter_price_cents) == ("over", 110000)
    assert v.talking_point == "That's above what Lumen Audio can do. Offer $1,100 instead."
def test_second_concession_moves_three_quarters(): ...  # concessions_made=1 -> 115000
def test_within_ceiling():
    v = check_counter(offered_price_cents=120000, offered_videos=3, concessions_made=2, **KW)
    assert (v.verdict, v.suggested_counter_price_cents) == ("within", None)
    assert v.talking_point == "That fits. Agree in principle and say Lumen Audio will confirm in writing."
def test_fewer_videos_scales_ceiling(): ...  # 2 videos for 90000: ceiling for 2 = 80000 -> over; suggested <= 80000 and >= 66667 rounded down to dollars
def test_suggestion_never_above_ceiling(): ...  # concessions_made=10 -> suggested <= 120000
def test_channels(): ...  # default_channel("phone_ok", "+15551234567", True) == "call"; ("email_first", phone, True) -> "email"; ("phone_ok", None, True) -> "email"
def test_channel_violation(): ...  # opted-out wins; call without opt-in -> "No phone opt-in"; email -> None
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/core/test_brief_rules.py tests/core/test_thread_state.py tests/core/test_guardrails.py -v` → FAIL.

- [ ] **Step 3: Implement**

`field_error` rules: the e-mail regex is `^[^@\s]+@[^@\s]+\.[^@\s]+$`; `go_live_by` must be strictly after `today`; `None` is never an error (clearing a field is allowed).

`TRANSITIONS` (exact; M3/M4 add rows):
```python
TRANSITIONS = {
    "queued": frozenset({"drafting", "calling", "failed"}),
    "drafting": frozenset({"awaiting_reply", "failed", "queued"}),  # queued: restart sweep only
    "calling": frozenset({"in_call", "countered", "accepted", "declined", "awaiting_reply", "needs_review", "failed"}),
    "in_call": frozenset({"countered", "accepted", "declined", "awaiting_reply", "needs_review", "failed"}),
    "awaiting_reply": frozenset({"failed"}),
    "failed": frozenset({"queued"}),
}  # every other status: frozenset()
```
`check_counter` algorithm (exact):
```python
scale = offered_videos / brief_videos
ceiling = math.floor(ceiling_cents * scale)
ask = min(round(ask_cents * scale), ceiling)
if offered_price_cents <= ceiling:
    return CounterVerdict(verdict="within", suggested_counter_price_cents=None,
        talking_point=f"That fits. Agree in principle and say {brand_name} will confirm in writing.")
step = 1 - 0.5 ** (concessions_made + 1)          # 0.5, 0.75, 0.875, ...
suggested = (ask + math.floor((ceiling - ask) * step)) // 100 * 100   # whole dollars, rounded down
suggested = max(min(suggested, ceiling), min(ask, ceiling))
return CounterVerdict(verdict="over", suggested_counter_price_cents=suggested,
    talking_point=f"That's above what {brand_name} can do. Offer {format_cents(suggested)} instead.")
```

- [ ] **Step 4: Run them** → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/briefs.py backend/app/core backend/tests/core
git commit -m "feat(core): brief rules, thread state machine and negotiation guardrails"
```

---

### Task 4: Best-value ranking

**Files:**
- Create: `backend/app/schemas/board.py` (only `BestValue` for now; Task 15 adds the rest), `backend/app/core/ranking.py`
- Test: `backend/tests/core/test_ranking.py`

**Interfaces:**
- Produces `BestValue(thread_id: UUID, eligible: bool, rank: int | None, score: float | None, per_video_cents: int | None, reasons: list[str], ineligible_reason: str | None)`.
- Produces `RankInput` (frozen dataclass): `thread_id: UUID, status: str, terms: NegotiationTerms | None, terms_source: str | None, engagement_rate: float | None, similarity: float | None`.
- Produces `rank_threads(items: Sequence[RankInput], *, ceiling_cents: int, brief_videos: int, go_live_by: date) -> dict[UUID, BestValue]`.

- [ ] **Step 1: Write the failing tests**

```python
GO_LIVE = date(2026, 11, 14)
def t(id_, price, videos=3, go_live=GO_LIVE, status="countered", source="creator", eng=4.0, sim=0.5):
    return RankInput(id_, status, NegotiationTerms(videos=videos, price_cents=price, go_live_by=go_live,
                     stance="counter", source="call", confidence=0.9), source, eng, sim)
def test_spec_demo_priya_beats_arjun_on_price():
    # Priya: $1,100 for 3 (367/video), a week late; Arjun: $1,200 for 3 (400/video), on time (spec §3 step 6)
    r = rank_threads([t(PRIYA, 110000, go_live=GO_LIVE + timedelta(days=7)), t(ARJUN, 120000)],
                     ceiling_cents=120000, brief_videos=3, go_live_by=GO_LIVE)
    assert r[PRIYA].rank == 1 and r[PRIYA].per_video_cents == 36667 and "Lowest $/video" in r[PRIYA].reasons
    assert r[ARJUN].rank == 2 and "Meets go-live date" in r[ARJUN].reasons
def test_over_budget_ineligible(): ...  # price 130000 -> eligible False, ineligible_reason "Over budget", rank None
def test_fewer_videos_ineligible(): ...  # videos 2 -> "Fewer videos than asked"
def test_brand_terms_or_open_status_ineligible(): ...  # source "brand", or status "awaiting_reply", or terms None -> "No creator terms yet"
def test_single_eligible_scores_full_value(): ...  # rank 1, score 1.0 when on time
def test_ties_broken_by_engagement(): ...
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement `rank_threads`**

- Eligibility checks run in this order (first failure is the reason): status in {countered, accepted} with `terms_source == "creator"` and terms with both `price_cents` and `videos`, else "No creator terms yet"; then `price_cents <= ceiling_cents`, else "Over budget"; then `videos >= brief_videos`, else "Fewer videos than asked".
- Among the eligible threads: `value = (max_pv - pv) / (max_pv - min_pv)`, or `1.0` when all are equal (pv is per-video cents). `timeline = 1.0` when `go_live_by` is unset or ≤ the brief date, else `max(0, 1 - days_late / 14)`. `audience` = the mean of the min-max-normalized available components (similarity, engagement; 1.0 when all values are equal), or `0.5` when neither is available.
- `score = round(0.5 * value + 0.25 * timeline + 0.25 * audience, 4)`. Rank by score descending, then engagement descending, then `thread_id`.
- Reasons, in this order: "Lowest $/video" (pv == min), "Meets go-live date" (timeline == 1.0), "Strongest audience match" (audience is the max and more than one thread is eligible).

- [ ] **Step 4: Run them** → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/board.py backend/app/core/ranking.py backend/tests/core/test_ranking.py
git commit -m "feat(core): best-value ranking with reason chips"
```

---

### Task 5: Adapters — ElevenLabs agents and Resend email

**Files:**
- Modify: `backend/app/adapters/elevenlabs.py`, `backend/app/api/deps.py`, `backend/tests/fakes.py`, `backend/tests/conftest.py` (fixture `fake_email`)
- Create: `backend/app/adapters/email.py`
- Test: `backend/tests/core/test_elevenlabs_client.py` (extend), `backend/tests/core/test_email_client.py`, `backend/tests/core/test_conversation_snapshot.py`

**Interfaces:**
- Produces in `app/adapters/elevenlabs.py`:
  - `class CallPlacementFailed(Exception)`. ElevenLabs refused the call; `str(exc)` is its message.
  - `ConversationSnapshot(BaseModel)`: `conversation_id: str, status: str` (one of `initiated`, `in-progress`, `processing`, `done`, `failed`), `turns: list[TranscriptTurn], duration_secs: int | None, summary: str | None`, plus property `user_spoke: bool` (true when any `user` turn has non-blank text).
  - `snapshot_from_payload(data: dict[str, Any]) -> ConversationSnapshot`. Pure; used for both the SDK response (`model_dump(mode="json")`) and the webhook's `data`. Turns come from `data["transcript"]`: keep only items with a non-blank `message`, mapped to `TranscriptTurn(role=item["role"], text=message.strip(), t=item["time_in_call_secs"])`. **Tool calls and tool results are dropped** (Ruling 4). `duration_secs` comes from `metadata.call_duration_secs`, `summary` from `analysis.transcript_summary`.
  - `ElevenLabsPort` gains `async mint_conversation_token(agent_id: str) -> str` (via `conversational_ai.conversations.get_webrtc_token(agent_id=...)` → `.token`), `async place_call(*, agent_id: str, phone_number_id: str, to_number: str, dynamic_variables: dict[str, str]) -> str` (via `conversational_ai.twilio.outbound_call(..., conversation_initiation_client_data=ConversationInitiationClientDataRequestInput(dynamic_variables=...))`; raises `CallPlacementFailed(response.message)` when `not response.success` or there is no `conversation_id`), and `async get_conversation(conversation_id: str) -> ConversationSnapshot` (via `conversational_ai.conversations.get(conversation_id=...)`). SDK/transport errors raise the existing `ElevenLabsUnavailable`.
- Produces in `app/adapters/email.py`: `OutboundEmail(to: str, sender: str, reply_to: str | None, subject: str, html: str, text: str, headers: dict[str, str] = {})`, `class EmailRejected(Exception)`, `class EmailUnavailable(Exception)`, `EmailPort.send(email: OutboundEmail, *, idempotency_key: str) -> str` (the Resend email id), and `ResendClient(settings)`, which raises `ValueError` without `resend_api_key`.
- Produces `deps.get_email() -> EmailPort` (lru_cache; HTTP 503 `email_unavailable` when unconfigured).
- Produces fakes: `FakeElevenLabs` gains `conversation_tokens: list[str]` (agent ids asked), `calls: list[dict]` (kwargs of each `place_call`), `call_failure: Exception | None`, `snapshots: dict[str, ConversationSnapshot]` (tests set them; a missing id raises `ElevenLabsUnavailable`), and returns conversation ids `conv_1`, `conv_2`, …. `FakeEmail`: `sent: list[tuple[OutboundEmail, str]]`, `failures: dict[str, Exception]` keyed by recipient, `crash_after_send: bool` (records the send, then raises `RuntimeError("crash")`). It returns `email_{n}` and **dedupes by idempotency key** (same key → same id, not appended), like Resend. Fixture `fake_email(app)` overrides `get_email`.

- [ ] **Step 1: Write the failing tests**

`test_email_client.py` (respx on `https://api.resend.com/emails`):
```python
async def test_send_posts_resend_payload_with_idempotency_key(respx_mock): ...
    # asserts JSON {"from","to":[to],"subject","html","text","reply_to","headers"}, headers Authorization "Bearer k", "Idempotency-Key"
    # returns the "id" from the 200 response
async def test_reply_to_omitted_when_none(respx_mock): ...
async def test_422_raises_rejected_without_retry(respx_mock): ...   # one call; EmailRejected message includes Resend's "message"
async def test_429_then_200_retries(respx_mock): ...                # two calls; returns id
async def test_500_three_times_raises_unavailable(respx_mock): ...
def test_requires_api_key(): pytest.raises(ValueError, ResendClient, Settings(_env_file=None))
```
`test_conversation_snapshot.py`:
```python
RAW = {"conversation_id": "c1", "status": "done",
       "transcript": [{"role": "agent", "message": "Hi Arjun", "time_in_call_secs": 0},
                      {"role": "agent", "message": None, "time_in_call_secs": 5,
                       "tool_calls": [{"tool_name": "check_counter"}],
                       "tool_results": [{"result_value": "{\"suggested_counter_price_usd\": 1100}"}]},
                      {"role": "user", "message": " three for thirteen hundred ", "time_in_call_secs": 7}],
       "metadata": {"call_duration_secs": 95}, "analysis": {"transcript_summary": "Countered at $1,300."}}
def test_turns_drop_tool_traffic():
    s = snapshot_from_payload(RAW)
    assert [t.model_dump() for t in s.turns] == [{"role": "agent", "text": "Hi Arjun", "t": 0.0},
                                                  {"role": "user", "text": "three for thirteen hundred", "t": 7.0}]
    assert "1100" not in s.model_dump_json()
def test_user_spoke(): ...  # only agent turns -> False
def test_duration_and_summary(): ...
```
`test_elevenlabs_client.py` (stub the SDK client like the M1 tests do): `test_place_call_passes_dynamic_variables`, `test_place_call_unsuccessful_raises_call_placement_failed`, `test_mint_conversation_token_returns_token`, `test_get_conversation_maps_snapshot`.

- [ ] **Step 2: Run them to see them fail** (`uv run pytest tests/core/test_email_client.py tests/core/test_conversation_snapshot.py tests/core/test_elevenlabs_client.py -v`) → FAIL.

- [ ] **Step 3: Implement**

`ResendClient` uses one `httpx.AsyncClient(timeout=15.0)` and a tenacity retry like `GeminiClient`: 3 attempts, `wait_exponential_jitter(initial=0.5, max=4.0)`, retrying 429/5xx and network errors. Any other 4xx raises `EmailRejected(<Resend "message">)` immediately; exhausted retries raise `EmailUnavailable`. The request body maps `sender` → `"from"` and omits `reply_to` when it is `None`.

- [ ] **Step 4: Run them** → PASS. Then run the whole backend suite (`uv run pytest -q`) → green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/adapters backend/app/api/deps.py backend/tests
git commit -m "feat(adapters): ElevenLabs calls and conversations, Resend email"
```

---

### Task 6: The thread event log

**Files:**
- Create: `backend/app/modules/threads/__init__.py`, `backend/app/modules/threads/repo.py`
- Test: `backend/tests/db/test_thread_repo.py`

**Interfaces:**
- Consumes: `check_transition`, `NegotiationTerms`, `EventType`, `Actor`.
- Produces (every function takes an `asyncpg.Connection`; the caller owns the transaction):
  - `ThreadRef` (frozen dataclass): `id, batch_id, brand_id, creator_id: UUID`
  - `class StaleThread(Exception)`. The thread was not in an expected status; someone else moved it first.
  - `async load_ref(conn, thread_id: UUID) -> ThreadRef | None`
  - `async record_event(conn, thread: ThreadRef, *, type: EventType, actor: Actor, payload: dict | None = None, terms: NegotiationTerms | None = None, transcript_id: UUID | None = None, external_id: str | None = None) -> int | None`. Returns the new id, or `None` when `(type, external_id)` is already recorded (`ON CONFLICT (type, external_id) DO NOTHING RETURNING id`). `terms` is stored as `terms.model_dump(mode="json")`.
  - `async transition(conn, thread_id: UUID, *, expected: Collection[str], target: str, last_error: str | None = None, latest_terms: NegotiationTerms | None = None, latest_terms_source: Literal["brand", "creator"] | None = None) -> None`. Calls `check_transition(e, target)` for every `e` in `expected` before any SQL (`IllegalTransition`). Then it runs `UPDATE threads SET status = target, last_error = $, latest_terms = coalesce($, latest_terms), latest_terms_source = coalesce($, latest_terms_source) WHERE id = $ AND status = ANY($)`; 0 rows raises `StaleThread`.
  - `async apply_event(conn, thread: ThreadRef, *, expected: Collection[str], target: str | None, type: EventType, actor: Actor, payload=None, terms=None, transcript_id=None, external_id=None, last_error=None, latest_terms=None, latest_terms_source=None) -> bool`. Inside `async with conn.transaction():` (a savepoint when nested) it records the event; if the event was a duplicate it returns `False` without transitioning; otherwise it transitions when `target` is set and returns `True`. `StaleThread` propagates, which rolls back the event.
  - `async update_latest_terms(conn, thread_id: UUID, terms: NegotiationTerms, source: Literal["brand", "creator"]) -> None`. No status change.

- [ ] **Step 1: Write the failing tests** (`pytestmark = pytest.mark.db`; `factory` + `db_conn`)

```python
async def test_record_event_returns_id_and_stores_terms(db_conn, factory): ...
async def test_duplicate_external_id_returns_none(db_conn, factory): ...
async def test_transition_moves_status(db_conn, factory): ...
async def test_transition_from_unexpected_status_raises_stale(db_conn, factory): ...   # thread is 'queued', expected {'calling'}
async def test_illegal_transition_raises_before_sql(db_conn, factory): ...            # expected {'declined'} target 'queued'
async def test_apply_event_rolls_back_event_when_stale(db_conn, factory): ...         # no event row left behind
async def test_apply_event_duplicate_does_not_transition(db_conn, factory): ...
async def test_latest_terms_kept_when_not_given(db_conn, factory): ...
```

- [ ] **Step 2: Run them to see them fail** (`uv run pytest tests/db/test_thread_repo.py -v`) → FAIL.

- [ ] **Step 3: Implement `repo.py`** per the Interfaces.

- [ ] **Step 4: Run them** → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/threads backend/tests/db/test_thread_repo.py
git commit -m "feat(threads): append-only event log with conditional transitions"
```

---

### Task 7: Briefs API — create, get, patch, preview

**Files:**
- Modify: `backend/app/schemas/briefs.py`, `backend/app/main.py`, `backend/tests/conftest.py` (fixtures `new_brand_client`, `brief_cleanup`)
- Create: `backend/app/modules/briefs/__init__.py`, `repo.py`, `service.py`; `backend/app/api/routers/briefs.py`
- Test: `backend/tests/api/test_briefs.py`

**Interfaces:**
- Consumes: `BriefFields`, `brief_rules.*`, `pick_anchor_package`, `compute_delta`, `default_channel`, `call_allowed`, `channel_violation`, `package_summary` (`app.modules.discovery.service`), `PackageSummary`, `RuleViolation`.
- Produces in `app/schemas/briefs.py`:
  - `CreateBriefRequest(creator_ids: list[UUID] = Field(min_length=1, max_length=10))`
  - `BriefPatch(BriefFields)` plus `intake_conversation_id: str | None = None`. Only fields the client sent are applied (`model_fields_set`); an explicit `null` clears a field.
  - `DealBrief(BriefFields)` plus `id: UUID, status: BriefStatus, creator_ids: list[UUID], approved_at: datetime | None, batch_id: UUID | None, missing: list[str], violations: list[RuleViolation]`
  - `BriefCreatorPreview(creator_id: UUID, name: str, handle: str, initials: str, package: PackageSummary, delta: PackageDelta | None, default_channel: ChannelPlan, call_allowed: bool, excluded_reason: str | None)` and `BriefPreview(creators: list[BriefCreatorPreview])`
- Produces `BriefService(db: Database, brand_id: UUID)` with `create(creator_ids) -> DealBrief`, `get(brief_id) -> DealBrief`, `patch(brief_id, patch: BriefPatch, today: date) -> DealBrief`, `preview(brief_id, today: date) -> BriefPreview`. Service errors: `BriefNotFound`, `BriefLaunched`, `InvalidField(field, message)`, `UnknownCreators(ids: list[UUID])`. Dependency `my_briefs(user=require_role("brand"), db) -> BriefService` (finds the caller's brand; 409 `onboarding_required` if missing).
- Produces endpoints (all brand-only):
  - `POST /api/v1/briefs` → 201 `DealBrief`; 422 `{error: "unknown_creators", creator_ids}`
  - `GET /api/v1/briefs/{brief_id}` → `DealBrief`; 404 `brief_not_found`
  - `PATCH /api/v1/briefs/{brief_id}` → `DealBrief`; 422 `{error: "invalid_field", field, message}`; 409 `brief_launched`
  - `GET /api/v1/briefs/{brief_id}/preview` → `BriefPreview`
- Produces test fixtures: `new_brand_client` (a freshly onboarded second brand, like `new_creator_client`: role brand, company "Test Brand Co", category consumer_tech, product "Test Product", summary "A test product") and `brief_cleanup` (a list the test appends brief ids to; teardown deletes them, which cascades to batches/threads/events/transcripts).

- [ ] **Step 1: Write the failing tests** (`tests/api/test_briefs.py`; `brand_client` is the seeded Lumen Audio)

```python
async def test_create_prefills_from_brand_and_product(brand_client, brief_cleanup, seeded_ids): ...
    # body {"creator_ids": [priya, arjun]} -> 201; brand_name "Lumen Audio", product_name "Lumen Pods",
    # product_summary == DEMO_PRODUCT_SUMMARY, contact_email == DEMO_BRAND_EMAIL, status "draft",
    # missing starts with "deliverables_count"
async def test_create_dedupes_and_keeps_order(brand_client, brief_cleanup, seeded_ids): ...
async def test_create_rejects_unknown_creator(brand_client): ...        # 422 unknown_creators lists the bad id
async def test_creator_cannot_create_brief(creator_client): ...        # 403 wrong_role
async def test_other_brand_gets_404(brand_client, new_brand_client, brief_cleanup, seeded_ids): ...
async def test_patch_rejects_invalid_field_with_message(brand_client, brief_cleanup, seeded_ids): ...
    # {"go_live_by": "2020-01-01"} -> 422 {"error":"invalid_field","field":"go_live_by","message":"The go-live date must be in the future."}
    # and nothing else from the same body was saved
async def test_patch_ask_over_ceiling_saved_as_violation(brand_client, brief_cleanup, seeded_ids): ...
async def test_complete_brief_becomes_ready(brand_client, brief_cleanup, seeded_ids): ...
async def test_patch_after_launch_409(brand_client, api_db, brief_cleanup, seeded_ids): ...   # set status 'launched' via SQL
async def test_preview_deltas_and_default_channels(brand_client, brief_cleanup, seeded_ids): ...
    # after patching deliverables 3 short_video, ask $1,000, go-live +30 days:
    # Arjun default_channel "call", call_allowed True; Priya "email"; each delta.headline non-empty
async def test_preview_delta_null_until_ask_complete(brand_client, brief_cleanup, seeded_ids): ...
async def test_responses_never_expose_contact_or_floor(brand_client, api_db, brief_cleanup, seeded_ids): ...
    # for create, get, patch, preview: Priya's and Arjun's email, Arjun's phone and every floor_price_cents of their packages are absent from r.text
```
Add a `seeded_ids` fixture to `tests/conftest.py` that returns `{"priya": UUID, "arjun": UUID}` by handle (`priyareviews`, `arjuntech`), or skips with `NOT_SEEDED`.

- [ ] **Step 2: Run them to see them fail** (`uv run pytest tests/api/test_briefs.py -v`) → FAIL.

- [ ] **Step 3: Implement repo, service, router; include the router in `create_app`**

- `create`: the brand row gives `company_name` and `contact_email`; the brand's first product (by id) gives `name`, and `summary[:200]` (or `None`). Dedupe `creator_ids`, keeping their order. Every id must be a creator with at least one published package, otherwise raise `UnknownCreators`.
- `patch`: if the brief is launched, raise `BriefLaunched`. Run `field_error` on each sent field; on the first error raise `InvalidField` and save nothing. Otherwise update the sent fields and recompute `status`: `ready` if `is_launchable`, else `draft`.
- `missing` and `violations` are computed on every read, never stored.
- `preview`: for each creator in `creator_ids`, load the published packages plus `phone`, `phone_opt_in` and `contact_opt_out` (internal only; never returned) and pick the anchor with `pick_anchor_package(fmt=deliverables_format, videos=deliverables_count)`. The delta needs `deliverables_count`, `ask_price_cents` and `go_live_by`, otherwise it is `None`. `excluded_reason = "Opted out of contact"` when opted out.
- Ownership: a brief of another brand is `BriefNotFound` (404, never 403), so ids can't be probed.

- [ ] **Step 4: Run them** → PASS; then `uv run pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(briefs): create, read, patch and preview negotiation briefs"
```

---

### Task 8: Launch — batch, threads, reply tokens

**Files:**
- Modify: `backend/app/schemas/briefs.py`, `backend/app/modules/briefs/service.py`, `backend/app/api/routers/briefs.py`, `backend/app/api/deps.py` (`optional_gemini`), `backend/tests/conftest.py` (fixtures `launched_batch` and `fictional_ids`; `fake_gemini` also overrides `optional_gemini`)
- Create: `backend/app/core/reply_token.py`, `backend/app/modules/briefs/launch.py`
- Test: `backend/tests/core/test_reply_token.py`, `backend/tests/core/test_plan_launch.py`, `backend/tests/api/test_launch.py`

**Interfaces:**
- Produces schemas: `LaunchRequest(channels: dict[UUID, ChannelPlan] = {}, follow_up_policy: FollowUpPolicy = "off")`, `LaunchExclusion(creator_id: UUID, reason: str)`, `LaunchResponse(batch_id: UUID, thread_count: int, excluded: list[LaunchExclusion])`.
- Produces `new_reply_token() -> str` (16 characters from `abcdefghijklmnopqrstuvwxyz0123456789`, via `secrets.choice`) and `reply_address(token: str, domain: str) -> str` → `t-{token}@{domain}`.
- Produces in `launch.py`: `LaunchCandidate` (frozen dataclass: `creator_id, package_id: UUID, preferred_channel: PreferredChannel, phone: str | None, phone_opt_in: bool, contact_opt_out: bool`), `PlannedThread(creator_id, package_id, channel_plan)`, and `plan_launch(candidates: Sequence[LaunchCandidate], channels: Mapping[UUID, ChannelPlan]) -> tuple[list[PlannedThread], list[LaunchExclusion]]`. Opted-out creators are excluded even when a channel was given. A channel that breaks `channel_violation` raises `ChannelNotAllowed(creator_id, message)`. A missing entry gets `default_channel`.
- Produces `BriefService.launch(brief_id, req: LaunchRequest, *, today: date, embedding: list[float] | None, hold: bool = False) -> LaunchResponse`. Errors: `BriefLaunched`, `BriefIncomplete(missing, violations)`, `ChannelNotAllowed`, `NoCreators`. **`hold=True` is test-only**: it sets every new thread's `next_action_at` to `'infinity'` so a running dev worker can never claim it.
- Produces `deps.optional_gemini() -> GeminiPort | None` (None instead of 503 when there is no key).
- Produces endpoint `POST /api/v1/briefs/{brief_id}/launch` → 201 `LaunchResponse`. Errors: 409 `brief_launched`; 422 `{error: "brief_incomplete", missing, violations}`, `{error: "channel_not_allowed", creator_id, message}` or `{error: "no_creators"}`.
- Produces fixture `fictional_ids`: two seeded creators other than Priya and Arjun whose email ends in `@example.com` (e.g. `mayamakestech`, `danieldoesdevices`).
- Produces fixture `launched_batch` → `LaunchedBatch(brief_id, batch_id, threads: dict[str, UUID])`, keyed by handle `priyareviews`, `arjuntech`, `mayamakestech`. It creates the brief through the API and patches it complete: 3 × `short_video`, go-live today + 30 days, ask **$1,000** (100000), ceiling **$1,234** (123400; an unusual number so leak tests can search for it), negotiation_ask "Three short reviews for the Lumen Pods launch", flexibility `["timeline"]`. It then launches through `BriefService.launch(..., hold=True)` with channels Arjun `call`, Priya `email`, Maya `email`. The brief is deleted at teardown.

- [ ] **Step 1: Write the failing tests**

```python
def test_reply_token_shape(): ...        # len 16, alphabet only, 1000 calls -> 1000 distinct
def test_reply_address(): assert reply_address("abc", "in.collabio.dev") == "t-abc@in.collabio.dev"
def test_plan_defaults_channels(): ...   # phone_ok + opted-in phone -> call; email_first -> email
def test_plan_honours_explicit_email_for_phone_creator(): ...
def test_plan_rejects_call_without_opt_in(): ...   # ChannelNotAllowed(creator_id, "No phone opt-in")
def test_plan_excludes_opted_out(): ...  # excluded == [LaunchExclusion(id, "Opted out of contact")], not planned
```
`tests/api/test_launch.py`: every launch that **succeeds through the API** uses only `fictional_ids` (reserved `@example.com` addresses, email channel). A dev worker sharing the database could otherwise claim the threads and send real email or place a real call.
```python
async def test_launch_creates_batch_threads_and_queued_events(brand_client, api_db, brief_cleanup, fictional_ids): ...
    # body {"follow_up_policy": "suggest"} -> 201 {thread_count: 2, excluded: []}; threads 'queued', channel_plan 'email',
    # distinct reply_tokens; one 'queued' event per thread, actor 'brand'; brief 'launched' with approved_at;
    # batches.follow_up_policy 'suggest'; brief_embedding is not null
async def test_launch_incomplete_422_lists_missing(brand_client, brief_cleanup, fictional_ids): ...
async def test_launch_twice_409(brand_client, brief_cleanup, fictional_ids): ...
async def test_concurrent_launch_creates_one_batch(brand_client, api_db, brief_cleanup, fictional_ids): ...
    # asyncio.gather two POSTs -> sorted statuses [201, 409]; exactly one batches row for the brief
async def test_call_without_opt_in_422(brand_client, brief_cleanup, seeded_ids): ...  # Priya with "call" -> channel_not_allowed
async def test_launch_never_copies_ceiling(brand_client, api_db, brief_cleanup, fictional_ids): ...
    # ceiling 123400: row_to_json of the threads and their events contains neither "123400" nor "1,234"
async def test_launch_survives_gemini_failure(brand_client, api_db, fake_gemini, brief_cleanup, fictional_ids): ...
    # fake_gemini.embed_failure = GeminiUnavailable("down") -> 201 and brief_embedding is null
async def test_creator_cannot_launch(creator_client): ...  # 403
```

- [ ] **Step 2: Run them to see them fail** (`uv run pytest tests/core/test_reply_token.py tests/core/test_plan_launch.py tests/api/test_launch.py -v`) → FAIL.

- [ ] **Step 3: Implement**

The router computes the embedding **before** the service transaction: `await gemini.embed_query(f"{product_name}: {product_summary}. {negotiation_ask}")`. A `GeminiUnavailable` or `GeminiInvalidOutput`, or a `None` gemini, gives `None` with a warning log. `BriefService.launch` runs in one `db.transaction()` and does this:
1. `select … from public.briefs where id = $1 and brand_id = $2 for update` (none → `BriefNotFound`).
2. If launched, raise `BriefLaunched`.
3. If not `is_launchable`, raise `BriefIncomplete`.
4. Load the candidates: for every creator in `creator_ids`, its anchor package and contact flags.
5. Run `plan_launch`; an empty plan raises `NoCreators`.
6. Insert the batch, then one thread per plan entry (`reply_token=new_reply_token()`, `next_action_at = 'infinity'` if `hold` else null) and its `queued` event (actor `brand`).
7. `update briefs set status = 'launched', approved_at = now()`.

`unique (brief_id)` on batches backs up the row lock.

- [ ] **Step 4: Run them** → PASS; then `uv run pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(briefs): launch a brief into a batch of queued negotiation threads"
```

---

### Task 9: Outreach email — draft, render, send, unsubscribe

**Files:**
- Modify: `backend/pyproject.toml` / `backend/uv.lock` (`uv add jinja2`), `backend/app/main.py`, `backend/app/modules/threads/repo.py` (`fail_thread`)
- Create: `backend/app/core/contact.py`, `backend/app/modules/outreach/__init__.py`, `prompts.py`, `render.py`, `service.py`, `backend/templates/email/outreach.txt.j2`, `backend/templates/email/outreach.html.j2`, `backend/app/api/routers/unsubscribe.py`
- Test: `backend/tests/core/test_contact.py`, `backend/tests/core/test_outreach_render.py`, `backend/tests/api/test_outreach.py`, `backend/tests/api/test_unsubscribe.py`

**Interfaces:**
- Produces `is_reserved_address(email: str | None) -> bool`. True for `None`/blank, for domains equal to or ending in `example.com`, `example.net` or `example.org`, for domains ending in `.example`, `.test`, `.invalid` or `.localhost`, and for `localhost`; case-insensitive. Also `first_name(name: str) -> str` (the first whitespace-separated word).
- Produces `async fail_thread(conn, thread_id: UUID, reason: str) -> None` in `threads/repo.py`. When the thread's current status may move to `failed`, it applies a `failed` event `{"reason": reason}` with `last_error=reason`; otherwise it does nothing.
- Produces `EmailDraft(subject: str = Field(max_length=120), opener: str, ask_paragraph: str, rationale: str)`.
- Produces `OutreachContext` (frozen dataclass; **deliberately has no ceiling field**): `thread: ThreadRef, attempts: int, reply_token: str, brand_name: str, product_name: str, product_summary: str, negotiation_ask: str, deliverables_format: ContentType, ask_videos: int, ask_price_cents: int, go_live_by: date, flexibility: list[str], creator_name: str, creator_bio: str | None, creator_niches: list[str], creator_email: str | None, package_id: UUID, package: PackageTerms, delta: PackageDelta`, and `async load_outreach_context(conn, thread_id: UUID, today: date) -> OutreachContext`.
- Produces `OUTREACH_SYSTEM: str` and `outreach_prompt(ctx: OutreachContext) -> str`.
- Produces `RenderedEmail(subject: str, html: str, text: str)` and `render_email(ctx: OutreachContext, draft: EmailDraft, *, offer_url: str, unsubscribe_url: str) -> RenderedEmail`. It uses Jinja2 `Environment(loader=FileSystemLoader(<backend>/templates/email), autoescape=select_autoescape(["html"]))`.
- Produces `async send_outreach(db: Database, *, gemini: GeminiPort | None, email: Callable[[], EmailPort], settings: Settings, thread_id: UUID, today: date) -> None`. `email` is a factory, called only for a real send, so threads for reserved addresses work without Resend configured.
- Produces fixture `m2_settings` in `tests/conftest.py` (used again by Tasks 11–14). It overrides `get_settings` with `get_settings().model_copy(update={"elevenlabs_negotiation_agent_id": "agent_neg", "elevenlabs_phone_number_id": "phnum_1", "elevenlabs_tool_secret": "tool-secret", "elevenlabs_webhook_secret": "hook-secret", "elevenlabs_brief_agent_id": "agent_brief", "resend_from": "Lumen Audio <outreach@test.collabio.dev>"})` and returns it. From here on, routes and services take settings as `Annotated[Settings, Depends(get_settings)]` (or as a parameter) so the override applies.
- Produces `GET` and `POST /api/v1/unsubscribe/{reply_token}` → `HTMLResponse` 200 (no auth).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("email,reserved", [("maya@example.com", True), ("a@sub.example.org", True), ("x@foo.test", True),
    ("x@host.invalid", True), (None, True), ("", True), ("priya@gmail.com", False), ("me@examples.com", False)])
def test_is_reserved_address(email, reserved): ...
def test_render_contains_table_link_footer_and_unsubscribe(): ...
    # text and html both contain: "Review & respond in Collabio", offer_url, unsubscribe_url,
    # "This email was written with AI assistance on behalf of Lumen Audio.", the ask price "$1,000",
    # the listed price for the ask, and the package name
def test_render_escapes_html_in_creator_and_draft_text(): ...   # "<b>Maya</b>" appears escaped in html
async def test_send_outreach_sends_once_with_stable_idempotency_key(api_db, launched_batch, fake_gemini, fake_email, m2_settings): ...
    # Priya's thread moved to drafting; one EmailDraft queued -> fake_email.sent == 1 with key f"thread:{id}:email:0";
    # 'awaiting_reply'; events email_drafted (payload attempt 0, subject, body_text) then email_sent (delivered True,
    # external_id "email_1"); transcript kind 'email_out'; reply_to None (no inbound domain);
    # headers List-Unsubscribe and List-Unsubscribe-Post present
async def test_reserved_address_records_not_delivered(api_db, launched_batch, fake_gemini, fake_email, m2_settings): ...
    # Maya: the email factory is never called; email_sent payload {"delivered": False}; 'awaiting_reply'
async def test_existing_draft_reused_for_same_attempt(api_db, launched_batch, fake_gemini, fake_email, m2_settings): ...
    # crash_after_send -> RuntimeError propagates, thread still 'drafting'; run again with crash off ->
    # one Gemini call in total, one entry in fake_email.sent
async def test_email_and_prompt_never_mention_ceiling(api_db, launched_batch, fake_gemini, fake_email, m2_settings): ...
    # neither "123400" nor "1,234" appears in fake_gemini.calls[-1] system/prompt, the rendered html or the text
async def test_rejected_email_fails_thread_with_reason(api_db, launched_batch, fake_gemini, fake_email, m2_settings): ...
    # failures[priya_email] = EmailRejected("Invalid `to` field") -> 'failed', last_error "Email rejected: Invalid `to` field"
async def test_missing_gemini_fails_thread(api_db, launched_batch, fake_email, m2_settings): ...
    # gemini=None -> 'failed', last_error "Email drafting isn't configured (GEMINI_API_KEY)."
async def test_unsubscribe_sets_opt_out(client, api_db, launched_batch): ...   # Maya's token; teardown restores contact_opt_out
async def test_unsubscribe_unknown_token_shows_same_page(client): ...
```
Give the test module a helper `to_drafting(conn, thread_id)` that runs `transition(conn, thread_id, expected={"queued"}, target="drafting")`.

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Write `OUTREACH_SYSTEM`**

It must state:
- You write one outreach email from {brand} to one content creator about a paid collaboration.
- Personalise only from the creator's bio, niches and package as given; never invent facts about the creator.
- State the ask plainly: the number of videos, the format, the price and the go-live date, all exactly as given.
- The only prices you may write are the ask price and the creator's own listed prices as given. Never mention a budget, a maximum, a ceiling or any other number.
- `subject` is at most 80 characters and names the product. `opener` is at most 2 sentences, `ask_paragraph` at most 4, and `rationale` (why this creator fits) at most 2.
- Plain sentences only: no markdown, no greeting line, no sign-off. The template adds those.

`outreach_prompt` lists the brand, product name and summary, what to negotiate for, flexibility, the creator's name/bio/niches, the package one-liner, and the ask with its delta headline.

- [ ] **Step 4: Write the templates**

`outreach.txt.j2` (exact copy):
```
Hi {{ first_name }},

{{ draft.opener }}

{{ draft.ask_paragraph }}

{{ draft.rationale }}

Your package vs. this ask
  Videos:     {{ listed_videos }} in "{{ package_name }}" · asking for {{ ask_videos }}
  Price:      {{ listed_price }} listed for {{ ask_videos }} · offering {{ ask_price }}
  Go live by: {{ go_live_by }}

Review & respond in Collabio: {{ offer_url }}
Or simply reply to this email.

— {{ brand_name }} (via Collabio)

This email was written with AI assistance on behalf of {{ brand_name }}.
Don't want brand offers? Unsubscribe: {{ unsubscribe_url }}
```
`outreach.html.j2` carries the same content: paragraphs, a three-row table (Videos / Price / Go live by), a button-styled link "Review & respond in Collabio", and a small grey footer with the disclosure and an "Unsubscribe" link. Inline styles only, max width 560px, system font stack.

- [ ] **Step 5: Implement `send_outreach`**

1. Load the context in a read connection. The thread must be `drafting`; otherwise return (someone else has it).
2. Draft. Look for the newest `email_drafted` event with `payload.attempt == ctx.attempts` and rebuild the draft from `payload.draft`. If there is none, call `gemini.generate_structured(system=OUTREACH_SYSTEM, prompt=outreach_prompt(ctx), schema=EmailDraft)`. Failures: gemini `None` → fail "Email drafting isn't configured (GEMINI_API_KEY)."; `GeminiUnavailable`/`GeminiInvalidOutput` → fail "Couldn't write the email (model unavailable). Retry to try again.". On success, render and record `email_drafted` (payload `{"attempt", "subject", "body_text": rendered.text, "draft": {opener, ask_paragraph, rationale}}`).
3. If `is_reserved_address(ctx.creator_email)`: in one transaction, record `email_sent` (payload `{"delivered": false}`) and move to `awaiting_reply`. Stop.
4. If `settings.resend_from` is empty → fail "Email isn't configured (RESEND_FROM).". If `email()` raises `ValueError` or `HTTPException` → fail "Email isn't configured (RESEND_API_KEY).".
5. Send: `email_id = await port.send(OutboundEmail(to=creator_email, sender=resend_from, reply_to=reply_address(token, domain) if settings.resend_inbound_domain else None, subject, html, text, headers={"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}), idempotency_key=f"thread:{thread_id}:email:{attempts}")`. `EmailRejected` → fail `f"Email rejected: {exc}"`; `EmailUnavailable` → fail "Email service unavailable. Retry to try again.". Any other exception propagates; the orchestrator isolates it.
6. In one transaction: insert the transcript (`email_out`, `external_id=email_id`, subject, body_text), record `email_sent` (`external_id=email_id`, payload `{"delivered": true}`, `transcript_id`), and transition `drafting → awaiting_reply`.

"fail" means `fail_thread(conn, thread_id, reason)`. URLs: `offer_url = f"{settings.public_frontend_url}/creator/offers/{thread_id}"`, `unsubscribe_url = f"{settings.public_backend_url}/api/v1/unsubscribe/{reply_token}"`.

- [ ] **Step 6: Implement the unsubscribe router**

It looks up the thread by `reply_token`, sets `creators.contact_opt_out = true` for its creator, and always returns the same page: `<h1>You're unsubscribed</h1><p>Brands on Collabio won't contact you again.</p>`. Include it in `create_app` under `API_PREFIX`.

- [ ] **Step 7: Run the tests** → PASS; then `uv run pytest -q` → green.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app backend/templates backend/tests
git commit -m "feat(outreach): personalized outreach email with disclosure and unsubscribe"
```

---

### Task 10: Orchestrator worker, restart sweep, lifespan

**Files:**
- Create: `backend/app/workers/__init__.py`, `orchestrator.py`, `sweep.py`, `runtime.py`
- Modify: `backend/app/modules/threads/repo.py` (`claim_queued`), `backend/app/main.py`, `backend/app/api/routers/briefs.py` (wake after launch), `backend/README.md` (a "Workers" section with the shared-database warning)
- Test: `backend/tests/workers/__init__.py`, `backend/tests/workers/test_orchestrator.py`, `backend/tests/workers/test_sweep.py`, `backend/tests/api/test_lifespan.py` (extend)

**Interfaces:**
- Produces `ClaimedThread(id: UUID, channel_plan: str, status: str)` and `async claim_queued(conn, *, limit: int, batch_id: UUID | None = None) -> list[ClaimedThread]`. With `batch_id` (tests), it ignores `next_action_at`.
- Produces `Handler = Callable[[UUID], Awaitable[None]]` and `Orchestrator(db: Database, handlers: Mapping[str, Handler], *, concurrency: int = 5, poll_seconds: float = 1.0, batch_id: UUID | None = None)` with `async process_once() -> int`, `async run() -> None` and `wake() -> None`. The handler key is the thread's `channel_plan`; `email_then_call` uses the `email` handler (Ruling 16).
- Produces `SweepResult(requeued: int, failed: int)` and `async sweep_stuck(db: Database, *, stale_after: timedelta = timedelta(minutes=2)) -> SweepResult`.
- Produces `async start_workers(app: FastAPI, settings: Settings) -> None`, `async stop_workers(app: FastAPI) -> None` and `wake_orchestrator(app: FastAPI) -> None` (a no-op when no workers run). Running workers live on `app.state.workers` (`None` when not started).
- Produces fixture `launched_ten`: the same complete brief as `launched_batch`, over ten seeded fictional creators (`@example.com`, none of them Priya or Arjun), all on `email`, launched with `hold=True`. It returns `LaunchedBatch` and deletes the brief at teardown.

- [ ] **Step 1: Write the failing tests** (`pytestmark = pytest.mark.db`)

```python
async def test_claim_moves_email_to_drafting_and_call_to_calling(api_db, launched_batch): ...
async def test_launch_ten_with_one_failure(api_db, launched_ten): ...
    # spec §13: ten email threads; the email handler raises RuntimeError for one of them and records the others
    # Orchestrator(concurrency=5, batch_id=...): call process_once() until it returns 0 -> 9 handled once each;
    # the tenth is 'failed', last_error "Something went wrong while processing. Retry to try again.", plus a 'failed' event
async def test_failures_are_isolated_per_thread(api_db, launched_batch): ...
    # email raises for Priya; Maya's email and Arjun's call are still handled exactly once
async def test_two_orchestrators_never_share_a_thread(api_db, launched_batch): ...
    # gather(o1.process_once(), o2.process_once()) -> each thread handled exactly once in total
async def test_restart_mid_launch_sends_each_email_once(api_db, launched_batch, fake_gemini, fake_email, m2_settings): ...
    # claim; send_outreach for Priya with crash_after_send -> RuntimeError, still 'drafting';
    # sweep_stuck(stale_after=timedelta(0)) -> requeued >= 1; Orchestrator(real email handler, batch_id=...).process_once();
    # Priya 'awaiting_reply'; len(fake_email.sent) == 1; Priya's draft came from a single Gemini call
async def test_stuck_call_is_failed_not_redialed(api_db, launched_batch, fake_elevenlabs): ...
    # Arjun claimed to 'calling' with no conversation id; sweep(stale_after=0) -> 'failed',
    # last_error "Interrupted before the call was placed. Retry to call again."; fake_elevenlabs.calls == []
async def test_sweep_leaves_fresh_threads_alone(api_db, launched_batch): ...
async def test_workers_not_started_when_disabled(monkeypatch): ...   # WORKERS_ENABLED=0 -> app.state.workers is None after startup
async def test_lifespan_starts_and_stops_workers(monkeypatch): ...   # start_workers/stop_workers patched with recorders
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement**

`claim_queued` SQL (exact):
```sql
with next as (
  select id from public.threads
  where status = 'queued'
    and (($2::uuid is null and (next_action_at is null or next_action_at <= now()))
         or batch_id = $2::uuid)
  order by created_at, id
  for update skip locked
  limit $1
)
update public.threads t
set status = case when t.channel_plan = 'call' then 'calling' else 'drafting' end
from next
where t.id = next.id
returning t.id, t.channel_plan, t.status
```
- `process_once` claims up to `concurrency` threads, runs their handlers concurrently through `_run_one`, and returns the count.
- `run` loops until cancelled. It claims only the free slots, keeps a set of running tasks, then waits on an `asyncio.Event` (set by `wake`) or `poll_seconds`, whichever comes first.
- `_run_one(id, channel)` awaits the handler. It re-raises `asyncio.CancelledError`; any other exception is logged with `logger.exception` and handled with `fail_thread(conn, id, "Something went wrong while processing. Retry to try again.")`.
- `sweep_stuck`: threads in `drafting` with `updated_at < now() - stale_after` go back to `queued` via `transition(..., last_error="Resumed after a restart")`. Stale threads in `calling` with `call_conversation_id is null` go to `fail_thread(..., "Interrupted before the call was placed. Retry to call again.")`. Calls with a conversation id are left to the watcher (Task 11).
- `start_workers` builds the ports once: `GeminiClient` when `gemini_api_key` is set, else `None`; `ElevenLabsClient` when its key is set, else `None`; a lazy `ResendClient` factory. It registers `{"email": <send_outreach bound to the ports>}`, runs `sweep_stuck`, starts `Orchestrator.run()` as a task, and stores everything on `app.state.workers`. `stop_workers` cancels the tasks and awaits them.
- Lifespan: after `db.connect`, call `start_workers` when `settings.workers_enabled`; in `finally`, call `stop_workers` before closing the pool. `create_app` sets `app.state.workers = None`.
- The launch route calls `wake_orchestrator(request.app)` after a successful launch.
- README (exact copy): "Tests and the dev backend share the hosted database. Run the dev backend with `WORKERS_ENABLED=0` while you run `pytest`. Test fixtures launch with `hold=True` so a running worker can't claim their threads; the API launch tests use only fictional creators, whose email is never delivered."

- [ ] **Step 4: Run them** → PASS; then `uv run pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests backend/README.md
git commit -m "feat(workers): launch orchestrator with skip-locked claims and a restart sweep"
```

---

### Task 11: Calls — placement and the call watcher

**Files:**
- Create: `backend/app/modules/negotiation/__init__.py`, `backend/app/modules/negotiation/calls.py`, `backend/app/workers/call_watcher.py`
- Modify: `backend/app/modules/threads/repo.py`, `backend/app/workers/runtime.py`
- Test: `backend/tests/core/test_dynamic_variables.py`, `backend/tests/api/test_calls.py`, `backend/tests/workers/test_call_watcher.py`

**Interfaces:**
- Produces `CallContext` (frozen dataclass; **no ceiling**): `thread: ThreadRef, brand_name: str, product_summary: str, creator_name: str, phone: str | None, phone_opt_in: bool, package_name: str, package: PackageTerms, ask_videos: int, ask_price_cents: int, go_live_by: date, flexibility: list[str]`, and `async load_call_context(conn, thread_id: UUID) -> CallContext`.
- Produces `dynamic_variables(ctx: CallContext) -> dict[str, str]` with exactly these keys: `thread_id`, `creator_first_name`, `brand_name`, `product_summary`, `package_name`, `package_terms` (`package_one_liner`), `ask_videos` (digits), `ask_price` (`format_cents`), `go_live_by` (`"November 14, 2026"`), `flexibility` (`", ".join(...)`, or `"none"` when empty), `follow_up_context` (`""` in M2).
- Produces `async start_call(db: Database, *, elevenlabs: ElevenLabsPort | None, settings: Settings, thread_id: UUID, today: date) -> None`.
- Produces repo functions: `async count_calls_today(conn, brand_id: UUID, today: date) -> int` (`call_placed` events since UTC midnight of `today`), `async set_call_conversation(conn, thread_id: UUID, conversation_id: str) -> None`, `LiveCall(thread: ThreadRef, status: str, conversation_id: str)` and `async live_calls(conn, *, batch_id: UUID | None = None) -> list[LiveCall]`.
- Produces `CallWatcher(db: Database, elevenlabs: ElevenLabsPort, *, complete_call: Callable[[str, ConversationSnapshot], Awaitable[object]], poll_seconds: float = 2.0)` with `async check_once(*, batch_id: UUID | None = None) -> None` and `async run() -> None`. Task 13 adds intake polling.
- Consumes the `m2_settings` fixture (Task 9).

- [ ] **Step 1: Write the failing tests**

```python
def test_dynamic_variables_exact(): ...
    # keys == the 11 above; creator_first_name "Arjun"; ask_price "$1,000"; go_live_by "November 14, 2026"
def test_dynamic_variables_exclude_ceiling(): ...
    # context from a brief with ceiling 123400: no value contains "1,234", "123400" or "1234"
async def test_start_call_places_call_and_records_conversation(api_db, launched_batch, fake_elevenlabs, m2_settings): ...
    # Arjun claimed to 'calling'; fake_elevenlabs.calls[0] has agent_id "agent_neg", phone_number_id "phnum_1",
    # to_number == Arjun's phone and the dynamic variables; call_conversation_id "conv_1";
    # 'call_placed' event external_id "conv_1", payload has no phone; still 'calling'
async def test_unconfigured_calls_fail_with_reason(api_db, launched_batch, fake_elevenlabs): ...
    # last_error "Calls aren't configured (ELEVENLABS_NEGOTIATION_AGENT_ID, ELEVENLABS_PHONE_NUMBER_ID)."
async def test_daily_call_cap(api_db, launched_batch, fake_elevenlabs, m2_settings, monkeypatch): ...
    # count_calls_today patched to return 20 -> 'failed', "Daily call limit reached (20 calls)."; no call placed
async def test_call_placement_failure_recorded(api_db, launched_batch, fake_elevenlabs, m2_settings): ...
    # call_failure = CallPlacementFailed("invalid number") -> "Call couldn't be placed: invalid number"
async def test_in_progress_marks_in_call(api_db, launched_batch, fake_elevenlabs): ...   # 'call_started' external_id = conversation id
async def test_unanswered_call_fails_with_retry(api_db, launched_batch, fake_elevenlabs): ...
    # snapshot "done" with only agent turns while 'calling' -> 'failed', last_error "No answer."; complete_call not called
async def test_finished_call_handed_to_complete(api_db, launched_batch, fake_elevenlabs): ...  # user spoke -> complete_call once
async def test_processing_waits(api_db, launched_batch, fake_elevenlabs): ...
async def test_lookup_error_skipped(api_db, launched_batch, fake_elevenlabs): ...       # no snapshot -> no change, no exception
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement**

`start_call`:
1. Load the context; the thread must be `calling`.
2. If `count_calls_today >= MAX_CALLS_PER_BRAND_PER_DAY`, fail "Daily call limit reached (20 calls).".
3. If an agent or phone id is unset, or `elevenlabs is None`, fail "Calls aren't configured (ELEVENLABS_NEGOTIATION_AGENT_ID, ELEVENLABS_PHONE_NUMBER_ID).".
4. If `call_allowed(phone, phone_opt_in)` is false, fail "No phone opt-in.".
5. `place_call(...)`. `CallPlacementFailed` → fail `f"Call couldn't be placed: {exc}"`; `ElevenLabsUnavailable` → fail "Voice service unavailable. Retry to call again.".
6. In one transaction: `set_call_conversation` and record `call_placed` (actor `brand_agent`, `external_id=conversation_id`, payload `{}`; **never the phone number**).

`CallWatcher.check_once` handles each `live_calls` row; an exception on one row is logged and skipped:
- Fetch `snapshot = await elevenlabs.get_conversation(conversation_id)`.
- `in-progress` while the thread is `calling` → `apply_event(type="call_started", actor="system", expected={"calling"}, target="in_call", external_id=conversation_id)`.
- `done` or `failed` with `not snapshot.user_spoke` while the thread is `calling` → `apply_event(type="failed", actor="system", expected={"calling"}, target="failed", payload={"reason": "No answer."}, last_error="No answer.", external_id=conversation_id)`.
- `done` or `failed` otherwise → `await complete_call(conversation_id, snapshot)`.
- `initiated` / `processing` → nothing.

Runtime: register `"call"` → `start_call` bound to the ports, and start `CallWatcher.run()` when ElevenLabs is configured. Until Task 13, `complete_call` is a placeholder that logs "call completion arrives in Task 13"; Task 13 replaces it.

- [ ] **Step 4: Run them** → PASS; then `uv run pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(negotiation): place outbound agent calls and watch them to the end"
```

---

### Task 12: Agent server tools — `check_counter` and `log_offer`

**Files:**
- Modify: `backend/app/schemas/negotiation.py`, `backend/app/api/deps.py` (`require_tool_secret`), `backend/app/main.py`
- Create: `backend/app/modules/negotiation/tools.py`, `backend/app/api/routers/webhooks.py`
- Test: `backend/tests/api/test_agent_tools.py`

**Interfaces:**
- Produces schemas:
  - `CheckCounterRequest(thread_id: UUID, price_usd: float = Field(gt=0), videos: int = Field(ge=1), conditions: str = "")`
  - `CheckCounterResponse(verdict: Literal["within", "over"], suggested_counter_price_usd: int | None, talking_point: str)`
  - `LogOfferRequest(thread_id: UUID, price_usd: float | None = Field(None, gt=0), videos: int | None = Field(None, ge=1), go_live_by: str = "", conditions: str = "", stance: Stance, speaker: Literal["creator", "agent"])`
  - `LogOfferResponse(logged: bool)`
- Produces `async check_counter_tool(db, req) -> CheckCounterResponse` and `async log_offer_tool(db, req) -> LogOfferResponse`. Errors: `ThreadNotFound`, `ThreadNotInCall`.
- Produces `deps.require_tool_secret(settings, x_collabio_tool_secret: Annotated[str | None, Header()] = None) -> None`: 503 `tools_unconfigured` when the setting is empty, 401 `invalid_tool_secret` on mismatch (`hmac.compare_digest`).
- Produces endpoints (no JWT; tool secret): `POST /api/v1/webhooks/elevenlabs/tools/check-counter` → `CheckCounterResponse` and `POST /api/v1/webhooks/elevenlabs/tools/log-offer` → `LogOfferResponse`. Both return 404 `thread_not_found` and 409 `thread_not_in_call`.

- [ ] **Step 1: Write the failing tests** (Arjun's thread from `launched_batch`, claimed to `calling`; header `X-Collabio-Tool-Secret: tool-secret`)

```python
async def test_tools_require_secret(client, m2_settings): ...        # missing or wrong header -> 401
async def test_tools_unconfigured_503(client): ...                    # tool secret empty -> 503
async def test_over_suggests_midpoint_in_dollars(client, m2_settings, api_db, launched_batch): ...
    # ask $1,000, ceiling $1,234, 3 videos; price_usd 1300, videos 3 ->
    # {"verdict": "over", "suggested_counter_price_usd": 1117,
    #  "talking_point": "That's above what Lumen Audio can do. Offer $1,117 instead."}; threads.concessions == 1
async def test_second_over_moves_up(client, m2_settings, api_db, launched_batch): ...  # second call -> 1175
async def test_within(client, m2_settings, api_db, launched_batch): ...                # 1200 -> "within", suggested None
async def test_not_in_call_409(client, m2_settings, launched_batch): ...                # Priya's queued thread
async def test_check_counter_result_not_stored(client, m2_settings, api_db, launched_batch): ...
    # thread_events count unchanged; no thread_events or threads row for the thread contains "1117" or "111700"
async def test_log_offer_appends_event_and_latest_terms(client, m2_settings, api_db, launched_batch): ...
    # speaker creator, 1300, 3 videos -> 'call_offer_logged' actor 'creator', terms.price_cents 130000, source "call";
    # threads.latest_terms price 130000, latest_terms_source 'creator'; still 'calling'
async def test_agent_offer_sets_brand_source(client, m2_settings, api_db, launched_batch): ...  # actor 'brand_agent', source 'brand'
async def test_log_offer_ignores_unparseable_date(client, m2_settings, api_db, launched_batch): ...  # "next friday" -> null date, 200
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement**

`check_counter_tool` runs in one transaction:
1. Lock the thread `for update`. Its status must be `calling` or `in_call` (Ruling 5), otherwise raise `ThreadNotInCall`.
2. Through the batch, read the brief's `budget_ceiling_cents`, `ask_price_cents`, `deliverables_count` and `brand_name`.
3. Run `check_counter(..., offered_price_cents=round(price_usd * 100), concessions_made=thread.concessions)`.
4. On `over`, run `update threads set concessions = concessions + 1`.

Return the suggestion as `suggested // 100` dollars. **Record no event** (Ruling 4).

`log_offer_tool`:
- `go_live_by` comes from `date.fromisoformat`, or `None` if that raises; `conditions` are the comma-split, stripped, non-empty parts.
- Build `NegotiationTerms(videos, price_cents=round(price_usd * 100) if price_usd else None, go_live_by, conditions, stance, source="call", confidence=0.9)`.
- Record `call_offer_logged` (actor `creator` or `brand_agent`, payload `{"speaker": speaker}`, `terms`). When price or videos is present, run `update_latest_terms` with source `creator` (speaker creator) or `brand` (speaker agent).

- [ ] **Step 4: Run them** → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(negotiation): check_counter and log_offer server tools for the call agent"
```

---

### Task 13: Post-call — structurer, signed webhook, transcripts

**Files:**
- Create: `backend/app/core/signatures.py`, `backend/app/modules/negotiation/prompts.py`, `structurer.py`, `completion.py`
- Modify: `backend/app/api/routers/webhooks.py`, `backend/app/workers/call_watcher.py` (intake polling), `backend/app/workers/runtime.py` (the real `complete_call`)
- Test: `backend/tests/core/test_signatures.py`, `backend/tests/core/test_structurer.py`, `backend/tests/api/test_post_call_webhook.py`, `backend/tests/workers/test_call_watcher.py` (extend)

**Interfaces:**
- Produces `verify_elevenlabs_signature(raw: bytes, header: str | None, secret: str, *, now: float, tolerance_s: int = 1800) -> bool` and `sign_elevenlabs_payload(raw: bytes, secret: str, timestamp: int) -> str`. The header looks like `t=<unix>,v0=<hex>`, where `<hex>` is `hmac_sha256(secret, f"{t}.{raw.decode()}")`. It is rejected when `t < now - tolerance_s`. Compare with `hmac.compare_digest`.
- Produces `CallAsk(videos: int, price_cents: int, go_live_by: date, format: ContentType, package_one_liner: str)`, `StructuredCall(terms: NegotiationTerms, summary: str = Field(max_length=600))`, `STRUCTURER_SYSTEM`, `structurer_prompt(*, ask: CallAsk, turns: list[TranscriptTurn], logged: list[NegotiationTerms]) -> str`, and `async structure_call(gemini: GeminiPort | None, *, ask: CallAsk, turns: list[TranscriptTurn], logged: list[NegotiationTerms]) -> StructuredCall | None`. It returns `None` when gemini is `None`, unavailable or gives invalid output, and forces `terms.source = "call"`.
- Produces `async complete_call(db, gemini, conversation_id: str, snapshot: ConversationSnapshot) -> bool`, `async complete_intake(db, conversation_id: str, snapshot: ConversationSnapshot, *, brief_id: UUID | None = None) -> bool` and `async fail_call(db, conversation_id: str, reason: str) -> None`.
- Changes `CallWatcher.__init__` to gain `complete_intake: Callable[[str, ConversationSnapshot], Awaitable[object]] | None = None`. When it is set, `check_once` also polls brief conversations.
- Produces endpoint `POST /api/v1/webhooks/elevenlabs/post-call` (no JWT; header `ElevenLabs-Signature`). It returns 503 `webhook_unconfigured`, 401 `invalid_signature`, or 200 `{"ok": true}` for every validly signed body (so ElevenLabs stops retrying).

- [ ] **Step 1: Write the failing tests**

```python
def test_signature_valid(): ...
def test_tampered_body_rejected(): ...
def test_wrong_secret_rejected(): ...
def test_stale_timestamp_rejected(): ...
def test_missing_or_malformed_header_rejected(): ...
def test_structurer_prompt_has_ask_and_turns(): ...   # contains "$1,000", "3 videos", "Creator: three for thirteen hundred"
async def test_structure_call_invalid_output_returns_none(fake_gemini): ...
async def test_structure_call_forces_source_call(fake_gemini): ...
# Webhook tests: Arjun's thread is 'in_call' with call_conversation_id "conv_1"; bodies signed with "hook-secret".
async def test_invalid_signature_401(client, m2_settings): ...
async def test_unconfigured_503(client): ...
async def test_post_call_records_call_ended_and_countered(client, m2_settings, api_db, launched_batch, fake_gemini): ...
    # queue StructuredCall(terms=counter 120000 for 3 videos, confidence 0.9, summary "Agreed $1,200 for three videos.")
    # -> 'countered', latest_terms.price_cents 120000, latest_terms_source 'creator'; transcript kind 'call' with turns;
    # 'call_ended' event with transcript_id, payload summary + duration_secs, external_id "conv_1"
async def test_duplicate_post_call_is_one_event(client, m2_settings, api_db, launched_batch, fake_gemini): ...
    # same body twice -> both 200; one 'call_ended'; len(fake_gemini.calls) == 1
async def test_low_confidence_needs_review(client, m2_settings, api_db, launched_batch, fake_gemini): ...
    # confidence 0.4 -> 'needs_review' and a 'needs_review' event, payload reason "Low confidence in the call terms."
async def test_structurer_failure_needs_review(client, m2_settings, api_db, launched_batch, fake_gemini): ...
    # queued dict that breaks the schema -> 'needs_review', reason "Couldn't read the call terms."
async def test_transcript_drops_tool_results(client, m2_settings, api_db, launched_batch, fake_gemini): ...
async def test_ceiling_never_stored_after_full_call(client, m2_settings, api_db, launched_batch, fake_gemini): ...
    # check_counter (over) + log_offer + post-call: nothing in thread_events payload/terms, the threads row or the
    # transcripts rows for the thread contains "123400" or "$1,234"
async def test_intake_transcript_stored(client, m2_settings, api_db, launched_batch, fake_gemini): ...
    # brief.intake_conversation_id "conv_brief"; webhook for conv_brief -> transcripts kind 'intake' with brief_id
async def test_unknown_conversation_is_200(client, m2_settings): ...
async def test_call_initiation_failure_fails_thread(client, m2_settings, api_db, launched_batch): ...
    # Arjun 'calling'; type "call_initiation_failure", data {conversation_id, failure_reason: "no-answer"} -> 'failed', "No answer."
async def test_watcher_completes_intake(api_db, launched_batch, fake_elevenlabs): ...
```
The webhook test body is `{"type": "post_call_transcription", "event_timestamp": <now>, "data": {"conversation_id": "conv_1", "status": "done", "transcript": [...], "metadata": {"call_duration_secs": 95}, "analysis": {"transcript_summary": "..."}, "conversation_initiation_client_data": {"dynamic_variables": {...}}}}`, using the transcript items from Task 5's `RAW`.

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Write `STRUCTURER_SYSTEM`**

It must state:
- You read a phone call between an AI agent (`Agent`) negotiating for a brand and a content creator (`Creator`).
- Return the creator's final position: the last terms the creator proposed or agreed to.
- `price_cents` is the total for all videos in integer US cents, and only if a number was said for it. Fill `videos` only if said, and `go_live_by` (YYYY-MM-DD) only if a date was agreed; otherwise use null. Never invent or infer numbers.
- `stance`: `counter` = the creator proposed different terms; `accept` = the creator agreed to the ask or to the agent's offer; `decline`; `question` = the creator needs information first; `no_commitment` = no position, e.g. "call me later"; `offer` = only the agent's offer stands and the creator did not answer it.
- `conditions` are short phrases for conditions the creator attached; `open_questions` are the creator's unanswered questions.
- `confidence` is between 0 and 1. It is below 0.6 when the call is short, garbled, a voicemail or contradictory.
- `summary` is 1–3 neutral sentences on what was agreed or left open. Never mention budgets, limits, tools or internal checks.
- The logged offers are hints recorded during the call; the transcript wins when they disagree.

`structurer_prompt` renders the ask (videos, `format_cents` price, go-live, format, package one-liner), the turns as `Agent:` / `Creator:` lines prefixed `[m:ss]`, and the logged offers as JSON. **No ceiling is passed in.**

- [ ] **Step 4: Implement completion and the webhook**

`complete_call`:
1. Read-only checks. Find the thread by `call_conversation_id`; if there is none, return `False`. If a `call_ended` event with this `external_id` exists, return `False`. If the thread's status is not `calling` or `in_call`, return `False`.
2. Load the `CallAsk` and the `call_offer_logged` terms. Call `structure_call` **outside** any transaction.
3. In one transaction:
   - Insert the transcript (`call`, `thread_id`, `external_id`, turns, summary = structured summary or `snapshot.summary`) with `ON CONFLICT (kind, external_id) DO NOTHING RETURNING id`. On a conflict, return `False`.
   - Run `apply_event(type="call_ended", actor="system", expected={"calling", "in_call"}, target=status_after_call(terms), payload={"summary": ..., "duration_secs": snapshot.duration_secs}, terms=terms, transcript_id=..., external_id=conversation_id, latest_terms=terms if terms and (terms.price_cents or terms.videos) else None, latest_terms_source="creator" if that else None)`.
   - If the target is `needs_review`, also record a `needs_review` event with payload `{"reason": ...}`: "Low confidence in the call terms." when terms came back with low confidence, "Couldn't read the call terms." when no terms came back.
   - `StaleThread` → return `False`.

`complete_intake`: find the brief by `intake_conversation_id = conversation_id`, or by `brief_id` when given, and insert an `intake` transcript (`brief_id`, turns, `snapshot.summary`) with `ON CONFLICT DO NOTHING`.

`fail_call`: the thread is found by conversation id and must be `calling`. Apply a `failed` event (`external_id=conversation_id`) with the reason.

Webhook:
1. Read `raw = await request.body()`. If the secret is unset → 503. If verification fails (`now=time.time()`) → 401.
2. On `post_call_transcription`: build the snapshot with `snapshot_from_payload({**data, "status": "done"})`. If `complete_call` returns `False`, run `complete_intake(..., brief_id=<data.conversation_initiation_client_data.dynamic_variables.brief_id when it parses as a UUID>)`.
3. On `call_initiation_failure`: `fail_call` with reason "Line busy." for `busy`, "No answer." for `no-answer`, else "Call couldn't connect.".
4. Ignore other types. Return `{"ok": True}`.

Watcher: `check_once` also polls each brief whose `intake_conversation_id` is set, whose `updated_at > now() - interval '1 hour'`, and which has no `intake` transcript for that id; when the snapshot is `done`, it runs `complete_intake`. Runtime: pass the real `complete_call` (bound to the Gemini port) and `complete_intake`.

- [ ] **Step 5: Run them** → PASS; then `uv run pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(negotiation): signed post-call webhook, call structurer and transcripts"
```

---

### Task 14: Agents as code, sync script, brief voice session

**Files:**
- Create: `backend/agents/brief_agent.json`, `backend/agents/negotiation_agent.json`, `backend/agents/tools/update_brief.json`, `show_creator.json`, `ready_to_launch.json`, `check_counter.json`, `log_offer.json`, `backend/scripts/sync_agents.py`, `backend/app/modules/briefs/voice_session.py`
- Modify: `backend/app/schemas/briefs.py` (`VoiceSessionResponse`), `backend/app/api/routers/briefs.py`
- Test: `backend/tests/core/test_agent_files.py`, `backend/tests/core/test_sync_agents.py`, `backend/tests/api/test_brief_voice_session.py`

**Interfaces:**
- Each tool file is exactly the body of `POST /v1/convai/tools`: `{"tool_config": {...}}`. Each agent file is the body of `POST /v1/convai/agents/create` plus one custom key, `"tool_names": [...]`, which the script swaps for `conversation_config.agent.prompt.tool_ids`. The placeholders `${PUBLIC_BACKEND_URL}`, `${ELEVENLABS_TOOL_SECRET}`, `${ELEVENLABS_BRIEF_VOICE_ID}` and `${ELEVENLABS_NEGOTIATION_VOICE_ID}` are substituted at sync time.
- Produces in `scripts/sync_agents.py`: `substitute(obj: Any, values: Mapping[str, str]) -> Any` (recursive over dicts, lists and strings; an unknown placeholder raises `KeyError` naming it); `async sync(http: httpx.AsyncClient, *, agents_dir: Path, values: Mapping[str, str], agent_ids: Mapping[str, str]) -> dict[str, str]` (agent file stem → agent id); and the CLI `uv run python -m scripts.sync_agents [--dry-run]`.
- Produces `VoiceSessionResponse(conversation_token: str, dynamic_variables: dict[str, str])`, `brief_dynamic_variables(brief: DealBrief, creators: Sequence[tuple[str, str]], today: date) -> dict[str, str]` (pairs of creator name and package one-liner), and endpoint `POST /api/v1/briefs/{brief_id}/voice-session` → `VoiceSessionResponse`. Errors: 409 `brief_launched`; 503 `voice_unavailable` when `elevenlabs_brief_agent_id` is unset or ElevenLabs fails.

- [ ] **Step 1: Write the agent and tool files**

`negotiation_agent.json` (exact):
```json
{
  "name": "Collabio Negotiation Agent",
  "tags": ["collabio"],
  "tool_names": ["check_counter", "log_offer"],
  "conversation_config": {
    "agent": {
      "language": "en",
      "first_message": "Hi {{creator_first_name}}, this is an AI assistant calling on behalf of {{brand_name}}. This call is recorded for both parties' records — is now a good time?",
      "dynamic_variables": {"dynamic_variable_placeholders": {
        "thread_id": "00000000-0000-0000-0000-000000000000", "creator_first_name": "Arjun",
        "brand_name": "Lumen Audio", "product_summary": "Wireless earbuds with 40-hour battery",
        "package_name": "Launch Duo", "package_terms": "2 videos/contract · $1,000",
        "ask_videos": "3", "ask_price": "$1,000", "go_live_by": "November 14, 2026",
        "flexibility": "timeline", "follow_up_context": ""}},
      "prompt": {
        "llm": "gemini-3.5-flash",
        "temperature": 0.3,
        "prompt": "You are an AI assistant phoning {{creator_first_name}}, a content creator, on behalf of {{brand_name}} about a sponsored-content deal for: {{product_summary}}.\nTheir package: {{package_name}} — {{package_terms}}.\nThe ask: {{ask_videos}} videos for {{ask_price}}, live by {{go_live_by}}. {{brand_name}} is flexible on: {{flexibility}}. {{follow_up_context}}\n\nHow to run the call:\n1. You already said you are an AI and that the call is recorded. If it is not a good time, ask when to call back, thank them and end the call.\n2. Explain the ask in one or two sentences, then listen.\n3. Whenever they name a price, a number of videos or a date, call log_offer with exactly what they said and speaker \"creator\".\n4. Before you agree to or answer any price, call check_counter with their price in US dollars and the number of videos. Follow its talking_point. The only prices you may ever say are the ask and a suggested_counter_price_usd that check_counter gave you.\n5. Agree in principle only after check_counter says \"within\", and then say that {{brand_name}} will confirm in writing. Nothing is final on this call.\n6. When you propose a counter, call log_offer with speaker \"agent\".\n7. Never mention budgets, ceilings, limits or tools. Keep every turn short and friendly. End the call politely once terms are settled or they decline."
      }
    },
    "tts": {"model_id": "eleven_flash_v2", "voice_id": "${ELEVENLABS_NEGOTIATION_VOICE_ID}"},
    "conversation": {"max_duration_seconds": 300}
  }
}
```
`brief_agent.json` uses the same shape with these values:
- `name` "Collabio Brief Agent"; `tool_names` `["update_brief", "show_creator", "ready_to_launch"]`; `voice_id` `${ELEVENLABS_BRIEF_VOICE_ID}`; `max_duration_seconds` 600.
- Placeholders for: `brief_id`, `brand_name`, `product_name`, `product_summary`, `contact_email`, `selected_creators_summary`, `current_brief_json`, `missing_fields`, `today`.
- `first_message`: `Hi! Let's finish the brief for {{product_name}}. Still to settle: {{missing_fields}}. Where would you like to start?`
- `prompt` (exact): "You are the Collabio brief assistant for {{brand_name}}. You help the brand finish a negotiation brief for {{product_name}} ({{product_summary}}). Selected creators: {{selected_creators_summary}}. The brief so far (JSON): {{current_brief_json}}. Still missing: {{missing_fields}}. Today is {{today}}.\n\nAsk only for what is missing, one short question at a time, in this order: how many deliverables and in what format, the go-live date, the opening ask price, the private budget ceiling, what to negotiate for, and where the brand is flexible.\nEvery time the brand gives a value, immediately call update_brief with one field and its value: deliverables_count (a whole number), deliverables_format (short_video, long_video, story or live), go_live_by (YYYY-MM-DD), ask_price_usd and budget_ceiling_usd (whole US dollars as digits, e.g. 1200 for \"twelve hundred\"), negotiation_ask (one sentence), flexibility (comma-separated from timeline, price, deliverables, or none), and product_summary, contact_email or deliverable_length_s when the brand changes them.\nIf update_brief returns an error, say it in plain words and ask again. When the brand names a creator, call show_creator. When nothing is missing, call ready_to_launch and tell the brand to press Launch; you cannot launch. The brand may also edit the card; you will get a note when they do. The budget ceiling is private to the brand; never present it as something creators will hear."

Tool files:
- `check_counter.json`: `{"tool_config": {"type": "webhook", "name": "check_counter", "description": "Check a price the creator named against what the brand can do. Call before answering any price.", "response_timeout_secs": 10, "api_schema": {"url": "${PUBLIC_BACKEND_URL}/api/v1/webhooks/elevenlabs/tools/check-counter", "method": "POST", "request_headers": {"X-Collabio-Tool-Secret": "${ELEVENLABS_TOOL_SECRET}"}, "request_body_schema": {"type": "object", "required": ["thread_id", "price_usd", "videos"], "properties": {"thread_id": {"type": "string", "dynamic_variable": "thread_id"}, "price_usd": {"type": "number", "description": "Total price the creator named, in US dollars"}, "videos": {"type": "integer", "description": "Number of videos for that price"}, "conditions": {"type": "string", "description": "Conditions they attached, in a few words; empty if none"}}}}}}`
- `log_offer.json`: the same `url`/header pattern for `/tools/log-offer`; description "Record terms someone just proposed on the call."; properties `thread_id` (dynamic variable), `price_usd` (number), `videos` (integer), `go_live_by` (string, "YYYY-MM-DD or empty"), `conditions` (string), `stance` (string, `enum` of the six stances), `speaker` (string, `enum` `["creator", "agent"]`); `required` `["thread_id", "stance", "speaker"]`.
- `update_brief.json`: `{"tool_config": {"type": "client", "name": "update_brief", "description": "Save one brief field the brand just gave.", "expects_response": true, "response_timeout_secs": 10, "parameters": {"type": "object", "required": ["field", "value"], "properties": {"field": {"type": "string", "enum": ["deliverables_count", "deliverables_format", "deliverable_length_s", "go_live_by", "ask_price_usd", "budget_ceiling_usd", "negotiation_ask", "flexibility", "product_summary", "contact_email"]}, "value": {"type": "string"}}}}}`
- `show_creator.json`: client tool; one required string parameter `creator_ref`; description "Highlight a selected creator the brand mentioned."; `expects_response: true`.
- `ready_to_launch.json`: client tool; `"parameters": {"type": "object", "properties": {}}`; description "Check whether the brief is complete."; `expects_response: true`.

- [ ] **Step 2: Write the failing tests**

```python
def test_agent_files_reference_known_tools(): ...       # every tool_names entry has tools/<name>.json
def test_negotiation_first_message_is_spec_copy(): ...  # equals the Global Constraints string
def test_negotiation_agent_has_no_ceiling_variable(): ...  # no "ceiling" inside any {{...}} or placeholder key
def test_substitute_replaces_and_reports_missing(): ...
async def test_tools_patched_not_duplicated(respx_mock, tmp_path): ...
    # GET /v1/convai/tools -> {"tools": [{"id": "tool_1", "tool_config": {"name": "check_counter"}}]}
    # -> one PATCH /v1/convai/tools/tool_1; POST /v1/convai/tools for each of the other four
async def test_tool_names_become_tool_ids(respx_mock, tmp_path): ...   # agent body has prompt.tool_ids, no tool_names
async def test_agent_created_when_unset_prints_env_line(respx_mock, tmp_path, capsys): ...
    # POST /v1/convai/agents/create -> {"agent_id": "agent_x"}; stdout has "ELEVENLABS_NEGOTIATION_AGENT_ID=agent_x"
async def test_agent_patched_when_set(respx_mock, tmp_path): ...       # PATCH /v1/convai/agents/agent_x
def test_dry_run_masks_secret(capsys): ...                            # no HTTP calls; "***" printed, the secret is not
def test_requires_https_backend_url(): ...                            # "http://localhost:8000" -> SystemExit with a message
async def test_voice_session_returns_token_and_variables(brand_client, m2_settings, fake_elevenlabs, brief_cleanup, seeded_ids): ...
    # fake_elevenlabs.conversation_tokens == ["agent_brief"]; dynamic_variables keys == {brief_id, brand_name, product_name,
    # product_summary, contact_email, selected_creators_summary, current_brief_json, missing_fields, today}
async def test_voice_session_503_without_agent(brand_client, fake_elevenlabs, brief_cleanup, seeded_ids): ...
async def test_voice_session_409_after_launch(brand_client, m2_settings, api_db, brief_cleanup, seeded_ids): ...
async def test_voice_session_other_brand_404(brand_client, new_brand_client, m2_settings, brief_cleanup, seeded_ids): ...
```

- [ ] **Step 3: Run them to see them fail** → FAIL.

- [ ] **Step 4: Implement the script and the endpoint**

`sync_agents`:
1. Use base `https://api.elevenlabs.io` with header `xi-api-key: <ELEVENLABS_API_KEY>`.
2. The values come from settings/env. Voice defaults: brief `EXAVITQu4vr4xnSDxMaL`, negotiation `JBFqnCBsd6RMkjVDRZzb`; check each with `GET /v1/voices/{id}` and exit with a clear message if it is missing. `PUBLIC_BACKEND_URL` must start with `https://` (except in `--dry-run`).
3. Tools: run `GET /v1/convai/tools` and match by `tool_config.name`, then PATCH or POST.
4. Agents: `brief_agent` ↔ `ELEVENLABS_BRIEF_AGENT_ID`, `negotiation_agent` ↔ `ELEVENLABS_NEGOTIATION_AGENT_ID`. PATCH `/v1/convai/agents/{id}` if the id is set; otherwise POST `/v1/convai/agents/create` and print `Set ELEVENLABS_…_AGENT_ID=<id> in backend/.env`.
5. Finally, run `GET /v1/convai/phone-numbers` and print one line per number, `phone_number_id  phone_number  label`, followed by `Set ELEVENLABS_PHONE_NUMBER_ID to the outbound-capable one.`

`brief_dynamic_variables`:
- `selected_creators_summary` = `"; ".join(f"{name} — {one_liner}")`.
- `current_brief_json` = `BriefFields` dumped as JSON (`mode="json"`, `exclude_none=True`).
- `missing_fields` = the `BRIEF_FIELD_LABELS` of the missing fields joined with `", "`, or `"nothing"`.
- `today` = ISO date; `brief_id` = `str(id)`.

- [ ] **Step 5: Run them** → PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/agents backend/scripts/sync_agents.py backend/app backend/tests
git commit -m "feat(agents): brief and negotiation agents as code, sync script, brief voice session"
```

---

### Task 15: Board API — batches, view model, thread detail, retry

**Files:**
- Modify: `backend/app/schemas/board.py`, `backend/app/main.py`
- Create: `backend/app/modules/board/__init__.py`, `repo.py`, `service.py`, `backend/app/api/routers/board.py`
- Test: `backend/tests/api/test_board.py`

**Interfaces:**
- Consumes: `compute_delta`, `rank_threads`, `package_summary`, `NegotiationTerms`, `TranscriptTurn`, `apply_event`, `wake_orchestrator`.
- Produces schemas:
  - `CreatorChip(id: UUID, name: str, handle: str, initials: str)`
  - `EmailPreview(subject: str, body_text: str, delivered: bool | None)`
  - `ThreadEventView(id: int, type: EventType, actor: Actor, created_at: datetime, payload: dict[str, Any], terms: NegotiationTerms | None)`
  - `TranscriptView(id: UUID, kind: str, created_at: datetime, subject: str | None, body_text: str | None, turns: list[TranscriptTurn], summary: str | None)`
  - `ThreadCard(id: UUID, creator: CreatorChip, channel_plan: ChannelPlan, status: ThreadStatus, package: PackageSummary, latest_terms: NegotiationTerms | None, latest_terms_source: Literal["brand", "creator"] | None, delta: PackageDelta, last_event: ThreadEventView | None, email: EmailPreview | None, live_offers: list[NegotiationTerms], best_value: BestValue | None, last_error: str | None, created_at: datetime, updated_at: datetime)`
  - `BriefSummary(brief_id: UUID, product_name: str, deliverables_count: int, deliverables_format: ContentType, ask_price_cents: int, budget_ceiling_cents: int, go_live_by: date, follow_up_policy: FollowUpPolicy)`
  - `BatchKpis(contacted: int, replied: int, countered: int, best_per_video_cents: int | None, launched_at: datetime)`
  - `BatchView(id: UUID, brief: BriefSummary, kpis: BatchKpis, threads: list[ThreadCard])`
  - `BatchListItem(id: UUID, brief_id: UUID, product_name: str, launched_at: datetime, thread_count: int, contacted: int, replied: int, countered: int)`
  - `ThreadDetail(card: ThreadCard, events: list[ThreadEventView], transcripts: list[TranscriptView])`
- Produces endpoints (brand-only; another brand's id → 404):
  - `GET /api/v1/batches` → `list[BatchListItem]`, newest first
  - `GET /api/v1/batches/{batch_id}` → `BatchView`; 404 `batch_not_found`
  - `GET /api/v1/threads/{thread_id}` → `ThreadDetail`; 404 `thread_not_found`
  - `POST /api/v1/threads/{thread_id}/retry` → `ThreadCard`; 409 `thread_not_failed`

- [ ] **Step 1: Write the failing tests**

```python
async def test_batch_view_shape_and_kpis(brand_client, launched_batch): ...
    # 3 cards, all 'queued'; kpis contacted 0, replied 0, countered 0, best_per_video_cents None; brief.budget_ceiling_cents 123400
async def test_cards_ranked_after_counters(brand_client, api_db, launched_batch): ...
    # via the repo: Priya calling->countered with $1,100 for 3 (source creator, call_ended event) and Arjun with $1,200 for 3
    # -> threads[0] is Priya with best_value.rank 1 and "Lowest $/video"; kpis.best_per_video_cents 36667, countered 2, replied 2
async def test_email_preview_and_delivery_flag(brand_client, api_db, launched_batch): ...  # Maya not delivered -> email.delivered False
async def test_live_offers_listed(brand_client, api_db, launched_batch): ...              # two call_offer_logged -> 2 offers, oldest first
async def test_thread_detail_events_and_transcripts(brand_client, api_db, launched_batch): ...  # events ascending by id; transcripts newest first
async def test_retry_failed_requeues(brand_client, api_db, launched_batch): ...
    # failed Arjun with a call_conversation_id -> 200; 'queued', attempts 1, last_error None,
    # call_conversation_id None, next_action_at None; a 'retried' event with actor 'brand'
async def test_retry_non_failed_409(brand_client, launched_batch): ...
async def test_other_brand_404(new_brand_client, launched_batch): ...
async def test_creator_403(creator_client, launched_batch): ...
async def test_board_never_exposes_contact_or_floor(brand_client, api_db, launched_batch): ...
    # list, view and detail responses: no creator email, no phone, no floor_price_cents of the anchor packages
async def test_list_batches_newest_first(brand_client, launched_batch): ...
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement**

- Ordering: eligible cards by `best_value.rank`, then the rest by `created_at`.
- `delta` = `compute_delta` for the anchor package against the brief's ask, with `latest=latest_terms` and today's date.
- `email` comes from the newest `email_drafted` payload (subject, body_text), with `delivered` from the newest `email_sent` payload.
- `live_offers` holds every `call_offer_logged` terms, oldest first; `last_event` is the newest event.
- KPIs: `contacted` = threads with an `email_sent` or `call_started` event; `replied` = threads with a `call_ended` event (M3 adds `email_received`); `countered` = status `countered`; `best_per_video_cents` = the minimum `per_video_cents` among the eligible `best_value`s.
- Ranking inputs: `similarity = 1 - (creators.embedding <=> batches.brief_embedding)` computed in SQL (null when either side is null); engagement = `creators.engagement_rate`.
- Retry runs in one transaction: `apply_event(type="retried", actor="brand", expected={"failed"}, target="queued")`, then `update threads set attempts = attempts + 1, last_error = null, call_conversation_id = null, next_action_at = null`. Afterwards it calls `wake_orchestrator(request.app)`.

- [ ] **Step 4: Run them** → PASS; then `uv run pytest -q` → green.

- [ ] **Step 5: Regenerate the frontend API types**

Run (in `frontend/`): `npm run api:gen`. Expected: `lib/api/openapi.json` and `lib/api/schema.d.ts` now contain `DealBrief`, `BriefPreview`, `BatchView`, `ThreadDetail` and the rest.

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests frontend/lib/api
git commit -m "feat(board): batch view model with ranking, thread detail and retry"
```

---

### Task 16: Voice router — brief and board screens

**Files:**
- Modify: `backend/app/schemas/voice.py`, `backend/app/modules/voice/prompts.py`, `backend/app/modules/voice/service.py`
- Test: `backend/tests/core/test_voice_service.py` (extend), `backend/tests/core/test_routed_intent_schema.py` (extend), `backend/tests/live/test_intent_live.py` (extend)

**Interfaces:**
- Produces:
  - `VoiceScreen` gains `"brief"` and `"board"`.
  - `NavigateRoute` gains `"/brand/batches"`.
  - `IntentKind` gains `"open_thread"` and `"sort"`.
  - New `BoardSortKey = Literal["best_value", "price", "status", "recent"]` and `OpenThreadArgs(creator_id: UUID)`.
  - `RoutedIntent` gains `open_thread_name: str | None = None` and `sort: BoardSortKey | None = None`.
  - `VoiceIntent` gains `open_thread: OpenThreadArgs | None = None` and `sort: BoardSortKey | None = None`, and its `navigate` becomes `NavigateRoute | None` (M1 follow-up, Task 9).
- `ALLOWED_INTENTS["brief"] = {"navigate"}` and `ALLOWED_INTENTS["board"] = {"open_thread", "sort", "navigate"}`.
- `DEFAULT_SUGGESTIONS["brief"] = ["Go to the board", "Go to discover"]` and `DEFAULT_SUGGESTIONS["board"] = ["Open Priya's thread", "Sort by price", "Sort by best value"]`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_open_thread_resolves_visible_creator(fake_gemini): ...
    # screen "board", visible [Priya, Arjun]; routed open_thread_name "priya" -> kind "open_thread", open_thread.creator_id == PRIYA
async def test_open_thread_unknown_name_is_unclear(fake_gemini): ...
async def test_sort_passes_through(fake_gemini): ...                  # sort "price"
async def test_open_thread_not_allowed_on_discover(fake_gemini): ...  # -> unclear
async def test_brief_screen_only_navigates(fake_gemini): ...          # routed sort on "brief" -> unclear
@pytest.mark.live
@pytest.mark.parametrize("phrase,kind", [("open Priya's thread", "open_thread"), ("sort by cheapest", "sort"),
                                          ("show me the best value first", "sort"), ("go to the board", "navigate")])
async def test_board_phrases(settings, phrase, kind): ...
```

- [ ] **Step 2: Run them to see them fail** (`uv run pytest tests/core/test_voice_service.py tests/core/test_routed_intent_schema.py -v`) → FAIL.

- [ ] **Step 3: Implement**

`_to_intent` gains two cases:
- `open_thread`: resolve `[routed.open_thread_name]` against `context.visible_creators` with `resolve_creator_refs`, and take the first id; if nothing resolves, return unclear.
- `sort`: pass the key through when it is set.

`ROUTER_SYSTEM` gains these rules:
- On the board, "open/show X's thread/card" is `open_thread` with `open_thread_name`.
- "Sort by price/cheapest" means `price`; "best value/best deal" means `best_value`; "by status" means `status`; "newest/latest" means `recent`.
- On the brief screen, only `navigate` applies (the conversation agent handles the brief itself).
- "Go to the board" navigates to `/brand/batches`.

Then run `npm run api:gen` in `frontend/`.

- [ ] **Step 4: Run them** → PASS. Optionally run `uv run pytest -m live tests/live/test_intent_live.py -v` (spends quota). If a live phrase fails, refine the prompt; never loosen the assertion.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests frontend/lib/api
git commit -m "feat(voice): board and brief screens for the intent router"
```

---

### Task 17: Frontend foundation — navigation, Review → brief, dock pause, realtime doorbell

**Files:**
- Modify: `frontend/components/shell/app-shell.tsx`, `frontend/components/voice/voice-screen.tsx`, `frontend/components/voice/voice-dock.tsx`, `frontend/app/brand/discover/review/page.tsx`
- Create: `frontend/lib/supabase/realtime.ts`
- Test: `frontend/tests/unit/app-shell.test.tsx`, `voice-screen.test.tsx`, `voice-dock.test.tsx`, `review-page.test.tsx` (extend each); `frontend/tests/unit/realtime.test.ts` (new)

**Interfaces:**
- Produces in `voice-screen.tsx`: `VoiceRegistry` gains `pause(reason: string): () => void`, `pausedReason(): string | null` and `subscribe(listener: () => void): () => void`. Pauses stack; the newest reason shows. Also two hooks: `useVoicePause(reason: string | null): void`, which pauses while `reason` is non-null and releases on change or unmount, and `useVoicePausedReason(): string | null`, which reads the store with `useSyncExternalStore` and returns `null` outside a provider.
- Produces in `realtime.ts`: `useBatchDoorbell(batchId: string, onRing: () => void, options?: { live?: boolean; pollMs?: number; debounceMs?: number }): void`. Defaults: `live` false, `pollMs` 10000, `debounceMs` 250.

- [ ] **Step 1: Write the failing tests**

```ts
// app-shell.test.tsx
it("brand rail links Board to /brand/batches", ...)
// voice-screen.test.tsx
it("a pause reports its reason until it is released", ...)
it("the newest of two pauses is the one shown", ...)
// voice-dock.test.tsx
it("a paused dock ignores Space and says why", ...)
    // useVoicePause("Voice is in the brief conversation") rendered beside the dock -> Space keydown does not call capture.start;
    // the dock shows the reason; the orb button is disabled
// review-page.test.tsx
it("Start negotiation creates a brief from the batch and opens it", ...)
    // api.POST("/api/v1/briefs", { body: { creator_ids: [...selection] } }) -> router.push("/brand/briefs/<id>")
it("Start negotiation is disabled with an empty batch", ...)
it("a failed brief creation shows a toast and stays on Review", ...)  // toast "Couldn't start the brief"
// realtime.test.ts (mock @/lib/supabase/browser)
it("subscribes to thread_events inserts for the batch", ...)
    // channel("thread-events:<id>").on("postgres_changes", {event:"INSERT", schema:"public", table:"thread_events", filter:"batch_id=eq.<id>"}, cb)
it("debounces a burst of inserts into one ring", ...)        // 5 inserts within 100 ms -> onRing once after 250 ms
it("rings once when the subscription opens, to catch up", ...)
it("polls while live and stops polling when not", ...)       // fake timers: live -> ring every 10 s; live false -> none
it("removes the channel on unmount", ...)
```

- [ ] **Step 2: Run them to see them fail** (`npm test -- app-shell voice-screen voice-dock review-page realtime`) → FAIL.

- [ ] **Step 3: Implement**

- Brand NAV becomes: Discover (`/brand/discover`), **Board** (`/brand/batches`, icon `LayoutGrid`, hint "Live negotiations"), Analytics (soon). The creator NAV is unchanged.
- In `voice-dock.tsx`, `beginPress` returns `false` while `useVoicePausedReason()` is non-null. `Readout` then shows the reason text, and the orb is `disabled`.
- `StartNegotiation` becomes a real `Button`, disabled when the batch is empty and showing a spinner while posting; remove the "Coming in M2" tooltip and note.
- `useBatchDoorbell` uses `getSupabaseBrowser().channel(...)`, debounces with `setTimeout`, rings on the `SUBSCRIBED` status, polls with `setInterval` while `live`, and on cleanup calls `supabase.removeChannel(channel)` and clears both timers.

- [ ] **Step 4: Run them** → PASS; then `npm run typecheck`, `npm run lint` and `npm test` → green.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): board nav, start a brief from Review, dock pause, realtime doorbell"
```

---

### Task 18: Brief page — the click path

**Files:**
- Create: `frontend/lib/brief/state.ts`, `frontend/components/brief/brief-card.tsx`, `field-editor.tsx`, `creators-panel.tsx`, `launch-bar.tsx`, `frontend/app/brand/briefs/[id]/page.tsx`
- Test: `frontend/tests/unit/brief-state.test.ts`, `brief-card.test.tsx`, `creators-panel.test.tsx`, `brief-page.test.tsx`

**Interfaces:**
- Consumes: `components["schemas"]["DealBrief" | "BriefPatch" | "BriefPreview" | "LaunchRequest" | "LaunchResponse"]`, `formatCents`, `contentTypeLabel`, `useVoiceScreen`, the `voice-missing` utility, `MoneyInput`, `Stepper`, `NativeSelect`, `ToggleGroup`, `Input`, `Tooltip`.
- Produces in `lib/brief/state.ts`:
  - `type BriefFieldKey` (the 12 editable keys of `BriefFields` except `flexibility_note`).
  - `BRIEF_FIELDS: { key: BriefFieldKey; label: string; required: boolean; private?: true }[]`. Order and labels (exact): Brand · Product · Product summary · Deliverables (`deliverables_count`, shown with its format) · Format (`deliverables_format`) · Video length (`deliverable_length_s`, optional) · Go live by · Budget ceiling (private) (`budget_ceiling_cents`, `private: true`) · Opening ask · The ask (`negotiation_ask`) · Flexible on (`flexibility`) · Reply-to contact (`contact_email`).
  - `fieldState(brief: DealBrief, key: BriefFieldKey, changed: ReadonlySet<BriefFieldKey>): "filled" | "missing" | "changed"`.
  - `changedFields(before: DealBrief | null, after: DealBrief): Set<BriefFieldKey>`.
  - `formatFieldValue(brief: DealBrief, key: BriefFieldKey): string`. Examples: `"3 short videos"`, `"$1,200"`, `"Nov 14, 2026"`, `"Timeline, Price"`, `"None"`, `"—"` when empty.
  - `launchLabel(count: number): string` → `"Launch to 10"` / `"Launch to 1"`.
  - `invalidFieldMessage(detail: unknown): { field: string; message: string } | null`, which reads a 422 `invalid_field` detail.
- Produces components:
  - `<BriefCard brief changed onEdit={(key, patch) => Promise<string | null>} />`. `onEdit` resolves to an error message or `null`.
  - `<CreatorsPanel creators channels onChannel={(creatorId, plan) => void} highlighted?: string | null />`.
  - `<LaunchBar count missing violations policy onPolicy onLaunch launching pulse?: boolean />`.

- [ ] **Step 1: Write the failing tests**

```ts
// brief-state.test.ts
it("lists fields in the brief's order with exact labels", ...)
it("formats values", ...)            // deliverables 3 + short_video -> "3 short videos"; 120000 -> "$1,200"; flexibility ["none"] -> "None"
it("marks a required empty field missing and a just-saved one changed", ...)
it("finds the fields a save changed", ...)
it("reads an invalid_field detail", ...)
// brief-card.test.tsx
it("shows missing fields with the pulse utility and filled ones plainly", ...)   // class voice-missing on missing rows
it("flashes the fields that just changed", ...)                                  // data-state="changed" for 1200 ms (fake timers), then "filled"
it("labels the ceiling as private", ...)                                         // "Budget ceiling (private)" + lock icon with sr text "Only you can see this"
it("shows a save error under the field and keeps the editor open", ...)
// creators-panel.test.tsx
it("shows each creator's package, delta headline and flags", ...)               // flags render as "Below base price", "Lead time conflict", "Estimated"
it("disables Call without opt-in and says why", ...)                             // tooltip "No phone opt-in"
it("greys out an opted-out creator", ...)                                        // "Opted out of contact", no channel control
// brief-page.test.tsx (mock useApi, next/navigation)
it("loads the brief and its preview", ...)
it("an edit patches the field, flashes it and refreshes the preview", ...)
it("Launch is locked until the brief is complete and lists what is missing", ...)  // tooltip "Still needed: go-live date, opening ask"
it("Launch posts channels and the follow-up policy, then opens the board", ...)
    // POST /api/v1/briefs/{id}/launch { channels: {arjun: "call", priya: "email"}, follow_up_policy: "suggest" } -> push("/brand/batches/<batch_id>")
it("a launched brief opens its board", ...)                                      // brief.batch_id set -> router.replace(...)
it("registers the brief screen for voice", ...)                                  // useVoiceScreen("brief", ...)
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement**

Layout: a two-column grid (`lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]`) that stacks on phones. Left is the BriefCard; the AgentSession slot sits above it and is added in Task 19. Right is the CreatorsPanel, with the LaunchBar sticky at the bottom.

- Each BriefCard row shows its label and value with a pencil button. The button opens an inline `FieldEditor`:
  - `MoneyInput` (dollars → cents) for money fields;
  - `Stepper` (min 1) for the count;
  - `NativeSelect` for the format;
  - `Input type="date"` for go-live;
  - `ToggleGroup` multiple for flexibility (choosing None clears the others);
  - `Input` for text and email.
- Every price and count uses the `num` utility.
- Follow-up policy is a `ToggleGroup` with Off / Suggest / Auto, captioned "Follow-ups start in M4." (Ruling 12).
- Channels are initialised from each preview row's `default_channel`.
- The page is a Client Component: `const { id } = useParams<{ id: string }>()`.

- [ ] **Step 4: Run them** → PASS; then typecheck, lint and test → green.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(brief): brief page with live card, creator deltas, channels and launch"
```

---

### Task 19: Brief agent session (conversation mode)

**Files:**
- Create: `frontend/lib/brief/agent-tools.ts`, `frontend/components/brief/agent-session.tsx`
- Modify: `frontend/app/brand/briefs/[id]/page.tsx`
- Test: `frontend/tests/unit/agent-tools.test.ts`, `frontend/tests/unit/agent-session.test.tsx`

**Interfaces:**
- Consumes: `ConversationProvider`, `useConversation`, `useConversationClientTool` from `@elevenlabs/react`; `POST /api/v1/briefs/{id}/voice-session`; `PATCH /api/v1/briefs/{id}`; `useVoicePause`; the `Orb`.
- Produces in `lib/brief/agent-tools.ts`:
  - `AGENT_FIELDS` (the 10 field names in `update_brief.json`).
  - `parseDollarsToCents(value: string): number | null`. Accepts `1200`, `1,200`, `$1,200`, `1200.50` and ` 1200 `; anything with letters, or a negative or zero amount, is `null`.
  - `agentFieldToPatch(field: string, value: string): { patch: BriefPatch } | { error: string }`.
  - `contextualUpdate(key: BriefFieldKey, brief: DealBrief): string` → `"The brand set {label} to {formatFieldValue} on the card."`
  - `matchCreator(ref: string, creators: { creator_id: string; name: string; handle: string }[]): string | null`. Case-insensitive; matches the full name, first name, or handle with or without `@`.
- Produces `<AgentSession briefId brief preview onSaved={(brief: DealBrief) => void} onHighlight={(creatorId: string) => void} onReady={() => void} />`. It wraps its body in `ConversationProvider`.

- [ ] **Step 1: Write the failing tests**

```ts
// agent-tools.test.ts (Review Focus 5)
it.each([["1200", 120000], ["1,200", 120000], ["$1,200", 120000], ["1200.50", 120050], [" 1200 ", 120000]])("parses %s", ...)
it.each(["twelve hundred", "1.2k", "-5", "0", ""])("rejects %s", ...)
it("maps ask_price_usd to ask_price_cents", ...)                 // {patch: {ask_price_cents: 100000}}
it("maps budget_ceiling_usd to budget_ceiling_cents", ...)
it("asks for digits when money is in words", ...)                // {error: "Give the amount in digits, for example 1200."}
it("accepts an ISO date and rejects other shapes", ...)          // "2026-11-14" ok; "next friday" -> {error: "Give the date as YYYY-MM-DD."}
it("validates count and format", ...)
    // "0" -> {error: "Give the number of deliverables as a whole number."};
    // "reel" -> {error: "Format must be one of short_video, long_video, story, live."}
it("splits flexibility and rejects unknown values", ...)
    // "timeline, price" -> ["timeline","price"]; "speed" -> {error: "Flexibility must be timeline, price, deliverables or none."}
it("rejects unknown fields", ...)                                // {error: "I can't set colour. Fields: deliverables_count, …"}
it("matches creators by first name and handle", ...)
// agent-session.test.tsx (mock @elevenlabs/react: capture the client tools and the startSession options)
it("starts a WebRTC session with the minted token and variables", ...)
    // click "Talk it through" -> POST voice-session -> startSession({conversationToken, connectionType: "webrtc", dynamicVariables})
it("records the conversation id on connect", ...)                // onConnect({conversationId:"conv_b"}) -> PATCH {intake_conversation_id:"conv_b"}
it("update_brief saves and reports what is still missing", ...)  // -> "Saved. Still missing: go-live date, opening ask"
it("update_brief returns the server's message on a 422", ...)
it("update_brief returns the parse error without calling the API", ...)
it("show_creator highlights a match and says so", ...)           // onHighlight(id); returns "Shown."; unknown -> "No creator by that name in this brief."
it("ready_to_launch reports missing fields or ready", ...)       // "ready" calls onReady
it("pauses the voice dock while connected", ...)                 // useVoicePausedReason() === "Voice is in the brief conversation"
it("sends a contextual update when the card is edited during a call", ...)
it("a blocked microphone shows a toast and keeps the card editable", ...)  // toast "Microphone blocked — edit the card instead"
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement**

Panel content:
- The `Orb` with `agentState`: connecting → `"thinking"`, connected while speaking → `"talking"`, connected otherwise → `"listening"`.
- A status line: "Connecting…", "Listening", "Speaking", or "Ended".
- Captions: the latest agent line and the latest user line, labelled "Agent" / "You", with `aria-live="polite"`.
- Buttons: "Talk it through", or "Resume" after a session has ended (both start a session), and "End conversation" while connected.

Tool handlers:
- `update_brief` → `agentFieldToPatch` → PATCH. On 200, call `onSaved` and return `Saved. Still missing: {labels}` (or `Saved. Nothing is missing.`). On 422, return the message. On a network error, return "Couldn't save that. Ask the brand to edit the card.".
- `show_creator` → `matchCreator` → `onHighlight`.
- `ready_to_launch` → return `"ready"` or `Still missing: …`.

Card edits made while connected (the page passes the changed keys) send `contextualUpdate` through `sendContextualUpdate`. While the conversation status is not `disconnected`, call `useVoicePause("Voice is in the brief conversation")`.

- [ ] **Step 4: Run them** → PASS; then typecheck, lint and test → green.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(brief): brief agent conversation with client tools and live captions"
```

---

### Task 20: Board page — cards, KPIs, realtime, reveal, re-rank

**Files:**
- Create: `frontend/lib/board/state.ts`, `frontend/components/board/status-pill.tsx`, `kpi-strip.tsx`, `thread-card.tsx`, `email-reveal.tsx`, `frontend/app/brand/batches/page.tsx`, `frontend/app/brand/batches/[id]/page.tsx`
- Add: ShinyText from react-bits: `npx shadcn@latest add @react-bits/ShinyText-TS-TW` (if the name differs, list the registry with `npx shadcn@latest view @react-bits/ShinyText-TS-TW` and pick the TS + Tailwind variant)
- Test: `frontend/tests/unit/board-state.test.ts`, `thread-card.test.tsx`, `board-page.test.tsx`, `batches-page.test.tsx`

**Interfaces:**
- Consumes: `BatchView`, `ThreadCard`, `BatchListItem`, `BoardSortKey` (generated), `useBatchDoorbell`, `CountUp`, `formatCents`, GSAP + `Flip`.
- Produces in `lib/board/state.ts`:
  - `STATUS_LABEL: Record<ThreadStatus, string>` (exact): queued "Queued", drafting "Writing email", awaiting_reply "Sent", calling "Calling…", in_call "In call", countered "Countered", accepted "Accepted", declined "Declined", needs_review "Needs review", failed "Failed", awarded "Booked", closed_lost "Closed", no_response "No response", follow_up_suggested "No reply · Call?".
  - `STATUS_TONE: Record<ThreadStatus, "neutral" | "active" | "positive" | "negative" | "attention">`.
  - `EVENT_LABEL: Record<EventType, string>`. These are used in Task 21: queued "Queued", email_drafted "Email written", email_sent "Email sent", call_placed "Call placed", call_started "Call connected", call_offer_logged "Offer logged during call", call_ended "Call ended", needs_review "Needs review", failed "Failed", retried "Retried"; any other type uses its words with the first letter capitalised.
  - `sortThreads(threads: ThreadCard[], key: BoardSortKey): ThreadCard[]`: `best_value` = rank ascending, eligible first, then `created_at`; `price` = latest per-video ascending, threads without terms last; `status` = the order of `STATUS_LABEL`; `recent` = `updated_at` descending. It never mutates its input.
  - `termsLine(terms: NegotiationTerms | null): string` → `"3 videos · $1,200 · live by Nov 14"` (parts omitted when null; `"No terms yet"` when nothing).
  - `lastEventLine(event: ThreadEventView | null, now: Date): string` → `"Email sent · 2 min ago"`, `"Offer logged during call · just now"`.
  - `isLive(threads: ThreadCard[]): boolean` (any status in queued, drafting, calling, in_call).
- Produces `<ThreadCard thread onOpen onRetry revealEmail: boolean />`, `<KpiStrip kpis now />`, `<StatusPill status />` and `<EmailReveal text animate />`.

- [ ] **Step 1: Write the failing tests**

```ts
// board-state.test.ts
it("sorts by best value with ineligible threads after", ...)
it("sorts by price per video with no-terms last", ...)
it("sorts by status order and by recency", ...)
it("does not mutate its input", ...)
it("formats terms and the last event", ...)
it("is live while any thread is queued, drafting, calling or in a call", ...)
// thread-card.test.tsx
it("shows status, terms, delta headline and last event", ...)
it("shows the drafted email, noting test addresses", ...)   // delivered false -> "Not delivered: test address"
it("shows a calling indicator and live offers during a call", ...)  // in_call + 2 live offers -> "In call", "$1,300 · 3 videos — creator"
it("marks the best value with its reasons", ...)            // "Best value" + "Lowest $/video"
it("shows the failure reason and a Retry button", ...)      // click -> onRetry(id)
it("prices use tabular numerals", ...)                      // price element has class "num"
// board-page.test.tsx (mock useApi, useBatchDoorbell)
it("loads the batch and renders a card per thread", ...)
it("refetches when the doorbell rings", ...)
it("passes live=true to the doorbell while threads are in flight", ...)
it("sort control reorders the cards", ...)
it("Retry posts and refetches", ...)
it("reveals a newly drafted email once", ...)               // revealEmail true on the first sighting, false after a refetch
// batches-page.test.tsx
it("lists batches newest first with counts and links", ...)
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement**

- **Board header:** the product name, the ask summary ("3 short videos · $1,000 · live by Nov 14"), and "Launched 4 min ago".
- **KpiStrip:** Contacted, Replied, Countered and Best $/video use `CountUp`; Time since launch ticks every 30 s.
- **Sort control:** a `ToggleGroup` with Best value / Price / Status / Recent; the default is Best value.
- **Grid:** `sm:grid-cols-2 xl:grid-cols-3`.
- **ThreadCard:**
  - StatusPill, a channel icon (`Mail` / `Phone`) and the creator name.
  - `termsLine` and the delta line (`latest_headline ?? headline`), coloured by gain or loss.
  - `lastEventLine`.
  - The email block shows `EmailReveal` over the first 320 characters of `body_text`.
  - A call indicator: a pulsing dot for `calling`, a solid red dot with the text "In call" for `in_call`, plus the list of live offers.
  - The Best value badge uses ShinyText, with the reasons as small chips.
  - A failed card shows `last_error` and a Retry button.
- **EmailReveal:** typewriter over about 1.2 s using `gsap.to({ n: 0 }, { n: text.length, onUpdate })`. Under reduced motion it shows the full text at once. Only the first sighting of a thread's email animates; keep a `Set` in a ref.
- **Motion:**
  - On the first load, the cards deal in once (`gsap.from(cards, { y: 24, opacity: 0, stagger: 0.06 })`).
  - When the order changes after a refetch or sort, capture `Flip.getState(cards)` before the render and run `Flip.from` after it.
  - Everything honours `prefers-reduced-motion` via `gsap.matchMedia()`.
- **Batches list:** a table of product, launched time, threads, contacted, replied and countered; each row links to `/brand/batches/{id}`. The empty state reads "No launches yet. Pick creators on Discover and start a negotiation." and links to `/brand/discover`.

- [ ] **Step 4: Run them** → PASS; then typecheck, lint and test → green.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(board): live negotiation board with KPIs, email reveal and re-rank"
```

---

### Task 21: Thread drawer and board voice

**Files:**
- Add: `npx shadcn@latest add sheet` (base-ui registry, like M1's dialog)
- Create: `frontend/components/board/thread-drawer.tsx`, `timeline.tsx`, `transcript-view.tsx`, `delta-table.tsx`
- Modify: `frontend/app/brand/batches/[id]/page.tsx`
- Test: `frontend/tests/unit/thread-drawer.test.tsx`, `frontend/tests/unit/board-voice.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/threads/{id}` (`ThreadDetail`), `POST /api/v1/threads/{id}/retry`, `EVENT_LABEL`, `useVoiceScreen("board", …)`.
- Produces `<ThreadDrawer threadId: string | null onClose refreshKey: number />`, which refetches whenever `refreshKey` changes (the page bumps it on every doorbell ring). Also `<Timeline events />`, `<TranscriptView transcript />` and `<DeltaTable delta />`.

- [ ] **Step 1: Write the failing tests**

```ts
// thread-drawer.test.tsx
it("loads the thread when opened and refetches on refreshKey", ...)
it("shows terms and the delta table", ...)
    // rows: Videos (listed / ask / latest), Price (listed for ask / ask / latest), $/video, Timeline (lead time vs days to go-live)
it("lists the timeline newest first with labels and times", ...)
it("expands a drafted email and a call summary", ...)
it("shows call turns as Agent and Creator with m:ss times", ...)
it("offers Retry only for failed threads", ...)
it("shows M3 actions disabled", ...)              // "Counter by voice", "Award", "Decline" disabled, tooltip "Coming in M3"
// board-voice.test.tsx
it("registers the board screen with the visible creators", ...)   // getContext().visible_creators == card creators
it("open_thread opens that creator's drawer", ...)
it("sort sets the sort control", ...)
```

- [ ] **Step 2: Run them to see them fail** → FAIL.

- [ ] **Step 3: Implement**

- The drawer is a right-hand `Sheet`, full width on phones and 480px on larger screens.
- Sections, in order: a header (creator, status pill, channel), then **Terms**, **Compared with their package** (DeltaTable plus flags), **Timeline**, **Transcripts** and **Actions**.
- `call` transcripts render each turn on one line, as "Agent"/"Creator" with `[m:ss]`. `email_out` transcripts render the subject and the body.
- The page keeps the open thread id in state; the drawer opens from a card click or the `open_thread` intent.
- `useVoiceScreen("board", () => ({ visible_creators: cards.map(c => ({ id: c.creator.id, name: c.creator.name, handle: c.creator.handle })) }), onIntent)` handles `open_thread` (find the card by `creator_id`) and `sort`.

- [ ] **Step 4: Run them** → PASS; then typecheck, lint and test → green.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(board): thread drawer with timeline, transcripts and delta; board voice"
```

---

### Task 22: M2 smoke test, run docs and the live checklist

**Files:**
- Create: `frontend/tests/e2e/m2.spec.ts`
- Modify: `backend/README.md` (an "M2: running negotiations" section), `frontend/README.md` (brief and board pages)
- Test: `npm run e2e -- m2.spec.ts`

**Interfaces:**
- Consumes everything above. The smoke test uses typed commands through the dock, like `m1.spec.ts`, and **only fictional creators**, so no real email is sent and no call is placed.

- [ ] **Step 1: Write the smoke test**

`m2.spec.ts`. Reuse the `signIn`, `say` and `whenHydrated` helpers by moving them to `tests/e2e/helpers.ts` and importing them in both specs.

1. Sign in as the demo brand.
2. On Discover, `say(page, "beauty creators")`, then `say(page, "select the top three")`.
3. Open Review and click **Start negotiation**; expect the URL to match `/brand/briefs/`.
4. Fill the brief by clicks: deliverables 2, format Short video, go-live = today + 30 (ISO), opening ask 800, budget ceiling 1000, the ask "Two short reviews for the Lumen Pods launch", flexible on Timeline.
5. Expect **Launch to 3** to be enabled, and click it; expect the URL to match `/brand/batches/`.
6. Within 90 s, all three cards show the status "Sent" and "Not delivered: test address". This needs a backend with workers and a Gemini key. Reserved addresses never touch Resend.
7. Open one card; the drawer timeline shows "Email written" and "Email sent".

- [ ] **Step 2: Run it**

Run the backend (`uv run uvicorn app.main:create_app --factory --port 8000`) and the frontend (`npm run dev`), then `npm run e2e -- m2.spec.ts`.
Expected: 1 passed. If the cards stay "Writing email", check the backend log for Gemini quota errors.

- [ ] **Step 3: Write the docs**

`backend/README.md`, section "M2: running negotiations":
- The new env variables and what each is for.
- The workers and the `WORKERS_ENABLED` warning (Task 10).
- How to sync the agents.
- How webhooks reach the backend. Use a quick tunnel: `cloudflared tunnel --url http://localhost:8000`. Its URL changes on every start, so set `PUBLIC_BACKEND_URL` and re-run the sync each time.

`frontend/README.md`: the Brief and Board pages, and the fact that realtime requires the Supabase session.

- [ ] **Step 4: Live checklist (the human runs this; Cursor stops here and hands over)**

1. **Resend:** verify a sending domain; set `RESEND_API_KEY` and `RESEND_FROM` (e.g. `Lumen Audio via Collabio <outreach@yourdomain>`). Leave `RESEND_INBOUND_DOMAIN` empty until M3.
2. **Secrets:** set `ELEVENLABS_TOOL_SECRET` to the output of `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. **Tunnel:** run `cloudflared tunnel --url http://localhost:8000`, set `PUBLIC_BACKEND_URL` to the printed `https://…trycloudflare.com` URL, and restart the backend.
4. **Agents:** run `uv run python -m scripts.sync_agents`. Copy the printed `ELEVENLABS_BRIEF_AGENT_ID`, `ELEVENLABS_NEGOTIATION_AGENT_ID` and the outbound `ELEVENLABS_PHONE_NUMBER_ID` into `backend/.env`. Run the sync again: it should now PATCH, not create.
5. **Post-call webhook:** in ElevenLabs → Agents Platform settings → Webhooks, add `{PUBLIC_BACKEND_URL}/api/v1/webhooks/elevenlabs/post-call` with the transcript and call-initiation-failure events, and copy its secret into `ELEVENLABS_WEBHOOK_SECRET`. The watcher completes calls even without this step, but brief transcripts and fast completion need it.
6. **Phone:** set `DEMO_HELPER_PHONE` (E.164) and re-seed: `uv run python -m scripts.seed --reset`. If the helper is outside the US, enable Twilio geo-permissions for that country. Place a test call at least a day before the demo.
7. **Rehearsal:**
   1. Discover: "tech creators doing short-form reviews under two thousand dollars", then select Arjun and Priya.
   2. Click Start negotiation and talk the brief through: 3 short videos, go-live in four weeks, ask $1,000, ceiling $1,200, flexible on timeline.
   3. Launch with Arjun on Call and Priya on Email.

   Expected:
   - Priya's inbox gets the email, with the disclosure footer and a working Unsubscribe link (don't click it on the demo account).
   - Arjun's phone rings with the AI disclosure line.
   - Say "three for thirteen hundred". The agent comes back with $1,100, and "Offer logged during call" appears on the card while you speak.
   - Settle at $1,200. When the call ends, the card turns **Countered** with "3 videos · $1,200" and a transcript in the drawer, and the KPI strip shows Replied 1 and Countered 1.

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/e2e backend/README.md frontend/README.md
git commit -m "test(m2): smoke test for brief to board, plus run docs and the live checklist"
```

---

## After M2

- Fold the remaining items in `docs/superpowers/plans/2026-10-10-m1-followups.md` into M3 planning.
- Before writing the M3 plan, re-read this plan's Rulings 4, 6, 11 and 16: M3 builds the offer desk, email replies and award on top of them.

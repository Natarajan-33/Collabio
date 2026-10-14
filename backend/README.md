# Collabio backend

FastAPI service behind Collabio, the voice-first marketplace where brands find creators and
creators publish packages. It owns auth checks, creator search (pgvector), the voice intent
router and package drafting (Gemini), and the realtime speech token (ElevenLabs).

There is no local Supabase stack and no Docker here: the API talks to a **hosted** Supabase
project (`collabio`) for Auth and Postgres.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you and manages the virtualenv)
- A hosted Supabase project with the M1 migration applied (see [Database](#database))
- A Gemini API key, and an ElevenLabs API key for realtime voice

## Setup

```bash
cd backend
uv sync
cp .env.example .env     # then fill it in; .env is git-ignored
```

> `.env.example` was written when a local stack was planned, and its comments still mention
> `supabase start`. Ignore them: use the hosted values below.

| Variable | What to put there |
| --- | --- |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_SECRET_KEY` | The project's secret key (`sb_secret_...`). Server only; used by the seed to create demo users. |
| `SUPABASE_DB_URL` | The **session pooler** string, see below. |
| `SUPABASE_JWKS_URL` | `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json` |
| `GEMINI_API_KEY` | Google AI Studio key. |
| `GEMINI_TEXT_MODEL` | `gemini-3.5-flash-lite` (the default). |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-2` (the default). |
| `ELEVENLABS_API_KEY` | Used to mint the browser's realtime speech-to-text token. |
| `FRONTEND_ORIGIN` | `http://localhost:3000`, the one origin allowed to call the API (CORS). |
| `DEMO_BRAND_EMAIL`, `DEMO_HELPER_EMAIL` | Emails for the demo brand and the demo creator Priya. |
| `DEMO_PASSWORD` | The one password all three demo logins share. |
| `DEMO_HELPER_PHONE` | A phone number in E.164 form (`+14155550123`), used as the second creator's contact. |

Never commit `.env` or paste its values anywhere. The settings objects keep secrets out of
their `repr()`, so they stay out of tracebacks too.

**Gemini quota.** The text model is `gemini-3.5-flash-lite`. The free tier has a small daily
request quota (it ran out on a larger model during M1, which is why this one is the
default). A `429` from Gemini means the day's quota is spent; wait for it to reset or use a
key with billing enabled. Search, voice commands and package drafting all call Gemini, and
return `503` when it is unavailable or the key is empty.

## Database

`SUPABASE_DB_URL` must be the **session pooler** connection string, not the direct
database host:

```
postgresql://postgres.<project-ref>:<db-password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
```

- The user is `postgres.<project-ref>` (not plain `postgres`) and the port is `5432`.
- The direct host (`db.<project-ref>.supabase.co`) is IPv6-only, so it fails from most
  networks. The pooler is reachable over IPv4.
- URL-encode special characters in the password. Copy the string from the dashboard
  (Connect, Session pooler) and replace `[YOUR-PASSWORD]`; while the placeholder is still
  there the app treats the database as not configured and DB endpoints return `503`.

The schema is one migration, `supabase/migrations/20261009081528_m1_core.sql` (tables,
row level security, `pgvector`, and the `match_creators` search function). It is already
applied to the `collabio` project. For a new project, apply that file once: paste it into the
dashboard SQL editor, or run `supabase link --project-ref <ref>` followed by
`supabase db push` (the CLI asks for the database password and needs no Docker for this).

## Seed the demo marketplace

```bash
uv run python -m scripts.seed --reset
```

This creates (or resets the password of) the three demo logins through the Auth Admin API,
then replaces, in one transaction, the 40 seeded creators with their packages and private
floors, plus the demo accounts' own rows:

| Account | Email | Lands on |
| --- | --- | --- |
| Brand (Lumen Audio) | `DEMO_BRAND_EMAIL` | `/brand/discover` |
| Creator Priya Raman (`priyareviews`) | `DEMO_HELPER_EMAIL` | `/creator/packages` |
| Creator Arjun Mehta (`arjuntech`) | `DEMO_HELPER_EMAIL` with `+arjun` added to the local part | `/creator/packages` |

`--reset` is required and is safe to repeat. It touches only the seeded creators and the
demo accounts; other users' rows are left alone. It never calls Gemini: each creator's
embedding comes from the committed cache `supabase/seed/embeddings.json`.

### Rebuilding the embedding cache

After editing `supabase/seed/creators.json`, refresh the cache and seed again:

```bash
uv run python -m scripts.build_embedding_cache   # needs GEMINI_API_KEY
uv run python -m scripts.seed --reset
```

Only creators whose embedding text changed are sent to Gemini ("embedded N new, M cached").
The seed refuses to run with a stale cache and says which creator to fix.

## Run

```bash
uv run uvicorn app.main:create_app --factory --port 8000
```

- Health: `GET http://localhost:8000/api/v1/health`
- Interactive docs: `http://localhost:8000/docs`

The app starts without a database or API keys; endpoints that need a missing piece answer
`503` (the startup log warns when the database is not configured). If you change a request or response model, regenerate
the frontend's types (see `frontend/README.md`, `npm run api:gen`).

## M2: running negotiations

M2 adds briefs, launch, outreach email (Resend), negotiation phone calls (ElevenLabs), and the
live board. Apply `supabase/migrations/20261010120000_m2_negotiation.sql` to the hosted
project if it is not there yet (`supabase db push` after `supabase link`).

Extra environment variables (see `backend/.env.example`):

| Variable | Purpose |
| --- | --- |
| `ELEVENLABS_BRIEF_AGENT_ID`, `ELEVENLABS_NEGOTIATION_AGENT_ID` | Agents Platform agent ids (from `scripts.sync_agents`). |
| `ELEVENLABS_PHONE_NUMBER_ID` | Outbound caller id for negotiation calls. |
| `ELEVENLABS_WEBHOOK_SECRET` | HMAC secret for the post-call webhook. |
| `ELEVENLABS_TOOL_SECRET` | Bearer token for `check_counter` / `log_offer` tool routes. |
| `RESEND_API_KEY`, `RESEND_FROM` | Outbound email (real domains only; `@example.com` is never sent). |
| `RESEND_INBOUND_DOMAIN` | Domain that receives creators' replies; used from M3, see [M3](#m3-the-deal-loop). |
| `PUBLIC_BACKEND_URL`, `PUBLIC_FRONTEND_URL` | Public URLs for email links and agent webhooks. |
| `WORKERS_ENABLED` | `0` while running `pytest` or a second dev API on the shared DB. |

Sync agent JSON to ElevenLabs after setting `PUBLIC_BACKEND_URL`:

```bash
uv run python -m scripts.sync_agents
```

Copy the printed agent ids and phone number into `.env`, then run the sync again (it should
PATCH, not create). Point ElevenLabs post-call webhooks at
`{PUBLIC_BACKEND_URL}/api/v1/webhooks/elevenlabs/post-call`. For local dev, expose the API
with a tunnel, for example `cloudflared tunnel --url http://localhost:8000`, set
`PUBLIC_BACKEND_URL` to the printed `https://…trycloudflare.com` URL, restart the API, and
re-run the sync whenever the tunnel URL changes.

## M3: the deal loop

M3 closes the loop: creators see their offers, counter, accept or decline; the brand counters
back, resolves replies that need a person, and awards a creator with a payment schedule;
both sides get a booked deal with the other's contact email. Email replies are parsed, and
every status change sends a notification through an outbox. No money moves (that is M4).

**1. Apply the migration** (adds deals, milestones, the outbox and the expiry columns). Use
the script, not the dashboard, so it is recorded and run in one transaction:

```bash
uv run python -m scripts.apply_migration supabase/migrations/20261014120000_m3_deal_loop.sql
```

**2. Environment** (see `backend/.env.example`):

| Variable | Purpose |
| --- | --- |
| `DEMO_MODE` | `1` shows the seeded fictional creators (registered or not) in Discover and lets a brief launch to them. Without it only creators with a login are discoverable and launching to an unregistered one fails with `creator_not_registered`. Development only; leave it unset in production. |
| `RESEND_INBOUND_DOMAIN` | The receiving domain for replies, e.g. `reply.<yourdomain>`. Offer emails carry a reply-to of `t-{token}@{RESEND_INBOUND_DOMAIN}`, and that token is the only thing that routes a reply to its thread. |
| `RESEND_WEBHOOK_SECRET` | The signing secret (`whsec_...`) of the Resend `email.received` webhook. Without it, or without the domain, the inbound endpoint answers `503 inbound_unconfigured`. |

**3. Workers.** Two more loops start with the API when `WORKERS_ENABLED` is on, beside the
launch orchestrator:

- **outbox-sender** delivers notification emails (a creator's offer moved, the brand
  countered, a booking) every 5 seconds, ten at a time. A failed send backs off
  (`30 s x 2^attempts`, five attempts) and reuses its Resend idempotency key, so a crash
  never double-sends. Mail to a reserved address (`@example.com`) is marked `skipped`.
- **expiry-sweep** runs every 60 seconds and moves offers still `awaiting_reply` past their
  deadline to `no_response`. **Offers expire after 7 days** (each batch stores its own `offer_ttl_days`, 1 to 30, default 7; the app has no screen for it yet);
  every move back into `awaiting_reply` restarts the clock, and a late reply reopens the
  thread.

> **Do not run the dev backend with workers on while you run `pytest` or the e2e specs
> unless you mean to.** Workers read the shared hosted database: stale queued rows can send
> real email or place a real phone call. Use `WORKERS_ENABLED=0` for tests; the e2e specs
> (`m2`, `m3`) are the exception and need workers on, so run them only against a freshly
> seeded database whose queue you know.

**4. Inbound webhook.** In Resend, point an `email.received` webhook at

```
{PUBLIC_BACKEND_URL}/api/v1/webhooks/resend/inbound
```

`PUBLIC_BACKEND_URL` must be reachable from the internet (a deploy, or the same tunnel as
the ElevenLabs webhooks in M2). The signature is checked first (Svix, 5 minute tolerance),
so a forged request never reaches the database. A reply from an address other than the
creator's goes to *Needs review* on the board instead of being trusted.

### Live checklist

The automated tests use fictional creators and never reach Resend or the phone. This list is
what only a person with real inboxes can check. It assumes the M2 setup (Resend sender,
`PUBLIC_BACKEND_URL`, tunnel) already works.

1. **DEMO_MODE.** Add `DEMO_MODE=1` to the dev `backend/.env`. Without it Discover shows only
   registered creators. Production leaves it unset.
2. **Receiving domain.** In Resend, Domains, enable receiving on a subdomain (for example
   `reply.<yourdomain>`), add the MX record it shows (lowest priority) and wait for it to
   verify. Set `RESEND_INBOUND_DOMAIN=reply.<yourdomain>`. A quick alternative is the
   account's own `<id>.resend.app` receiving domain.
3. **Webhook.** In Resend, Webhooks, add `{PUBLIC_BACKEND_URL}/api/v1/webhooks/resend/inbound`
   for `email.received`. Copy its signing secret into `RESEND_WEBHOOK_SECRET`, then restart
   the backend.
4. **Rehearsal.** Launch a brief to Priya by email. From the helper inbox, reply "I can do 3
   videos for $1,150 if go-live moves two weeks later". The board shows Priya *Countered*
   at $1,150 within seconds, and the presenter's inbox gets "Priya Raman countered: ...".
   Reply again from a different address: the card goes to *Needs review* with "The reply
   came from an address that isn't the creator's".
5. **Award.** Award Priya. The helper inbox gets "You're booked: Lumen Audio x ...", and both
   Deals pages show the payment schedule and each other's contact email.
6. **Browser smoke (optional, last).** With the stack up, workers on, `DEMO_MODE=1`, a Gemini
   key and a freshly seeded database (`uv run python -m scripts.seed --reset`), run from
   `frontend/`:

   ```bash
   npm run e2e -- m3.spec.ts
   ```

   It drives two browsers (the demo brand and Priya) through brief, launch, counter,
   counter, accept and award, with Maya (an `@example.com` address, never emailed) as the
   creator who is declined. Priya is launched by email, so it sends real email to
   `DEMO_HELPER_EMAIL` and notifications to the demo inboxes. Expected: `1 passed`. The spec
   was written against the UI but had not been run when this checklist was added; treat its
   first run as part of the check.

## Workers

When `WORKERS_ENABLED` is on (the default), the app starts the launch orchestrator with the
API. It claims queued negotiation threads (several at a time, with skip-locked claims, so
more than one process is safe) and sends each creator's outreach email. On startup a sweep
requeues threads a previous process left half-drafted and fails calls that were never placed;
a call is never re-dialed automatically. Launching a brief wakes the orchestrator at once;
otherwise it polls every second.

Tests and the dev backend share the hosted database. Run the dev backend with `WORKERS_ENABLED=0` while you run `pytest`. Test fixtures launch with `hold=True` so a running worker can't claim their threads; the API launch tests use only fictional creators, whose email is never delivered.

The test suite itself forces `WORKERS_ENABLED=0` (in `tests/conftest.py`), so the app lifespan
never starts a worker under `pytest`.

## Test and lint

```bash
uv run pytest -q                  # everything except live tests
REQUIRE_DB=1 uv run pytest -q     # the same, but a missing/unreachable database fails
uv run pytest -m live             # real Gemini and ElevenLabs calls; spends quota
uv run ruff check .
```

In PowerShell, set the variable first (`REQUIRE_DB=1 uv run ...` is POSIX-only):

```powershell
$env:REQUIRE_DB = "1"; uv run pytest -q
```

- Without `REQUIRE_DB=1`, tests that need the database **skip** when `SUPABASE_DB_URL` is
  empty, a placeholder, or unreachable. A database that is reachable but wrong (bad password,
  missing `vector` extension) still fails. Use `REQUIRE_DB=1` whenever you want to be sure
  the database tests really ran.
- The database tests run against the hosted project. They are read-only or clean up after
  themselves (each runs in a rolled-back transaction, or uses a throwaway creator that is
  deleted), so the seeded data survives a run.
- Live tests (`-m live`) are deselected by default, skip when their key is missing, and
  count against your Gemini/ElevenLabs quota.

## Layout

```
app/
  main.py            app factory, CORS, database pool lifespan
  config.py          Settings, read from the environment and backend/.env
  api/               routers (thin) and dependencies (auth, db, Gemini, ElevenLabs)
  modules/           services and repositories: discovery, me, packages, voice
  core/              pure rules: money, package rules, pricing, text helpers
  adapters/          db (asyncpg pool), gemini, elevenlabs, email (Resend)
  workers/           launch orchestrator, restart sweep, outbox sender, expiry sweep, start/stop with the app
  schemas/           Pydantic request/response models (the OpenAPI source)
scripts/             seed, build_embedding_cache, export_openapi
supabase/            migration and the seed dataset
tests/               api/, core/, db/, workers/ and live/
```

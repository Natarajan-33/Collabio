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
| `RESEND_INBOUND_DOMAIN` | Leave empty until M3 inbound reply parsing. |
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
  workers/           launch orchestrator, restart sweep, start/stop with the app
  schemas/           Pydantic request/response models (the OpenAPI source)
scripts/             seed, build_embedding_cache, export_openapi
supabase/            migration and the seed dataset
tests/               api/, core/, db/, workers/ and live/
```

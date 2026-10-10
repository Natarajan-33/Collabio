# Collabio frontend

Next.js 16 (App Router, Turbopack) and React 19 app for Collabio, the voice-first marketplace
where brands find creators and creators publish packages. Styling is Tailwind 4 with
shadcn/Base UI components; auth is Supabase (`@supabase/ssr`); data comes from the FastAPI
backend through a typed client (`openapi-fetch`); voice uses ElevenLabs Scribe in the browser.

> Next.js 16 has breaking changes from earlier versions. Before changing app code, read the
> relevant guide in `node_modules/next/dist/docs/` (see `AGENTS.md` at the repo root).

## Prerequisites

- Node 22 and npm
- The backend running on `http://localhost:8000` (see `backend/README.md`) and seeded with
  `uv run python -m scripts.seed --reset`
- The hosted Supabase project `collabio`. Docker is **not** required; there is no local
  Supabase stack.
- Chrome or Edge for voice (the microphone needs `localhost` or HTTPS)

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local     # .env.local is git-ignored
```

If `npm install` reports a peer dependency conflict, add `--legacy-peer-deps`: the lockfile was
produced with it.

`.env.example` already carries the project's public values. Everything in it is safe for the
browser: `NEXT_PUBLIC_` variables are inlined into the bundle, so never put a secret key or
an API key here.

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | The hosted project's URL. |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Its publishable (anon) key. |
| `NEXT_PUBLIC_API_URL` | The backend, `http://localhost:8000`. The backend's `FRONTEND_ORIGIN` must be this app's origin (`http://localhost:3000`). |
| `NEXT_PUBLIC_DEMO_MODE` | `1` lists the demo accounts under the sign-in form (emails only, never a password). Read at build time: restart `npm run dev` after changing it. |
| `DEMO_BRAND_EMAIL`, `DEMO_HELPER_EMAIL` | The emails the backend seed ran with, shown by the demo hint. Server-side only. |

For sign-up, the project's Auth settings must allow `http://localhost:3000/sign-in` as a
redirect URL (the confirmation email links there).

## Run

```bash
npm run dev          # http://localhost:3000
```

Start the backend first. Sign in with a seeded demo account (the password is `DEMO_PASSWORD`
from `backend/.env`, shared out of band):

- the brand lands on `/brand/discover`
- Priya Raman and Arjun Mehta land on `/creator/packages`

## Brief and Board (M2)

- **`/brand/briefs/[id]`** — edit the deal brief, preview creator deltas, talk to the brief
  agent (WebRTC), and **Launch** to a batch. While the brief agent is live, the Voice Dock
  pauses with a short reason.
- **`/brand/batches`** — list launches; **`/brand/batches/[id]`** — the live negotiation
  board (KPIs, sortable cards, email reveal, thread drawer). Board updates use Supabase
  Realtime inserts on `thread_events` as a doorbell to refetch the server view model; the
  signed-in Supabase session must be present in the browser.

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` / `build` / `start` | Develop, production build, serve the build. |
| `npm run test` | Unit and component tests (Vitest, `tests/unit/`). |
| `npm run typecheck` | `tsc --noEmit`; covers the app, the unit tests and the e2e files. |
| `npm run lint` | ESLint. |
| `npm run format` | Prettier on `.ts` and `.tsx`. |
| `npm run e2e` | Playwright smoke spec (`tests/e2e/`), see below. |
| `npm run api:gen` | Re-exports the backend's OpenAPI schema and regenerates `lib/api/openapi.json` and `lib/api/schema.d.ts`. Run it after changing backend request or response models, and commit the result. |

Before pushing: `npm run test && npm run typecheck && npm run lint && npm run build`.

## End-to-end smoke (Playwright)

`tests/e2e/m1.spec.ts` and `tests/e2e/m2.spec.ts` drive the real UI against a running stack,
using the Voice Dock's
text box instead of the microphone. Typing a command takes the same road as speaking
(`POST /api/v1/voice/command`), so everything but the microphone itself is covered. It has
three tests:

1. A brand signs in, types a discovery command, sees the chips (Consumer tech, Short video,
   `≤ $2,000`) and at least 10 creator cards, types "select the top ten", sees
   "10 selected", opens Review and gets 10 comparison columns.
2. Priya signs in, types a package dictation, names the package, publishes it and sees the
   "Published" badge.
3. A brand that opens `/creator/packages` is sent to `/brand/discover`.

`m2.spec.ts` walks a brand from Discover through a click-filled brief, launch, and board cards
showing **Sent** and **Not delivered: test address** (fictional `@example.com` creators only).
It needs `WORKERS_ENABLED=1` on the backend, a Gemini key, and the same demo env vars as M1.
Run a single file with `npm run e2e -- m2.spec.ts`.

**One-time setup.** Playwright needs its own browser build; the install is a download you run
once per machine:

```bash
npx playwright install chromium
```

**Run it.** Start the backend and the app (two terminals), then:

```bash
# Git Bash / macOS / Linux
export DEMO_BRAND_EMAIL=...  DEMO_HELPER_EMAIL=...  DEMO_PASSWORD=...   # the seeded logins
npm run e2e
```

```powershell
# PowerShell
$env:DEMO_BRAND_EMAIL = "..."; $env:DEMO_HELPER_EMAIL = "..."; $env:DEMO_PASSWORD = "..."
npm run e2e
```

Instead of exporting, you can put those three variables in `frontend/.env.e2e` (git-ignored,
loaded by `playwright.config.ts`; real environment variables win). Without them the spec skips
with a message saying what to set; credentials are never stored in the repo. Set
`E2E_BASE_URL` to test an app that is not on `http://localhost:3000`. After a failure,
`npx playwright show-report` opens the report with traces and screenshots.

Things to know:

- The tests call **real Gemini** through the backend, so `GEMINI_API_KEY` must be set in
  `backend/.env`, and the free tier's small daily quota applies. A run spends a handful of
  requests.
- The package test adds one **published package** (named `E2E smoke <timestamp>`) to Priya's
  account on every run. Nothing else is changed. `uv run python -m scripts.seed --reset`
  (in `backend/`) restores the seeded data.
- Tests run one at a time; the three accounts and the database are shared.

## Manual demo check

The microphone, the visuals and a few cross-screen details are not automated. Walk through
this once on a fresh seed, in Chrome:

- [ ] **Sign in as each demo account.** Brand lands on `/brand/discover`; Priya and Arjun on
      `/creator/packages`. Use **Sign out** in the left rail to switch accounts. A brand that
      opens `/creator/packages` is bounced back, and a creator that opens `/brand/discover`
      likewise.
- [ ] **Hold Space on Discover and say the demo query**: "tech creators doing short-form
      reviews under two thousand dollars". Your words appear as you speak; on release a
      "Heard:" chip shows what was understood, the filter chips light up (Consumer tech, Short
      video, `≤ $2,000`) and the grid re-sorts. Packages outside the filters look dimmed but
      stay readable.
- [ ] **Select the top ten**: say "select the top ten". The tray shows "10 selected".
- [ ] **Open review**: click **Review** (or say "open review"). Ten columns appear, the best
      value in each row is marked, and **Start negotiation** is disabled with "Coming in M2".
- [ ] **Creator dictates and publishes a package**: as Priya on Packages, hold Space and say
      "short videos, tech, two per contract for nine hundred, extra video three fifty, email
      first". The draft card fills in and the missing field (the name) is outlined. Type a
      name, **Publish**, and the package appears with a "Published" badge. To try the private
      floor, **Save draft** first (the floor field unlocks once the package is saved), set a
      floor, then publish: the floor shows only on Priya's own screen, never on a brand's.
      Then sign out, sign in as the brand and say "tech short videos under a thousand":
      Priya's new package appears, and no floor price is shown. (This is the publish, embed
      and brand-search path; the e2e spec stops at the badge.) Re-seed afterwards to remove
      the package.
- [ ] **Mic denied falls back to typing**: block the microphone for `localhost` in the browser
      (or dismiss the permission prompt) and hold Space. A message appears and the Dock
      switches to its text box; typing a command and pressing Enter works. The keyboard icon
      beside the Dock switches by hand at any time.
- [ ] **Light and dark**: press `d` (outside a text field) to flip the theme, and check
      Discover, Review and Packages in both. Text stays readable and nothing relies on colour
      alone.
- [ ] **Phone width**: narrow the window to about 390 px (browser device toolbar) and check
      Discover, Review and Packages in both themes. The page itself does not scroll
      sideways, the Dock and the selection tray stay reachable, and text stays readable.

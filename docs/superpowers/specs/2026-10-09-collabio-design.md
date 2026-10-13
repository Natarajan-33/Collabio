# Collabio — Design Spec (v1)

| | |
|---|---|
| **Date** | 2026-10-09 |
| **Status** | Approved in brainstorming; awaiting written-spec review |
| **Source brief** | `BUSINESS_USE_CASE.md` |
| **Path** | Architectural — one spec, one implementation plan per milestone |

---

## 1. Intent

### 1.1 What we are building
Collabio is a two-sided marketplace where **brands** negotiate sponsored-content deals with **creators**, using a voice-first workflow. A brand speaks its brief once; the system personalizes and runs negotiations with many creators in parallel by email and AI phone call, and the creator side compares every inbound offer against their own published packages and replies by voice.

### 1.2 Who this build is for
A **live demo / pitch**. One presenter drives the brand side; **one helper** plays creators (owns a phone and a second laptop). Every negotiation in the demo is genuine — **no simulated counterparties**. The build is above MVP quality but is not a production product.

### 1.3 What the user asked for (stated)
- New `frontend/` and `backend/` folders; stack chosen for the use case.
- Voice-first, **not** voice-only: voice is the fast input; the screen carries all information (cards, comparisons, transcripts, status).
- ElevenLabs for voice; Gemini embeddings for search/retrieval; Supabase for auth/DB/realtime.
- Frontend built with react-bits, canvas-ui, ElevenLabs UI, GSAP skills/registries — no generic "AI slop" look.
- A small number of excellent features rather than many shallow ones; scope later expanded by the user to include package editing, analytics, email-reply parsing, and email→call follow-ups.

### 1.4 Success criteria
1. The full chained demo (§3) runs end-to-end in ~6–7 minutes with one presenter and one helper.
2. Brand goes from "I have a product" to "10 creators contacted" in **under 3 minutes**, using only voice and clicks.
3. Every voice interaction that leads to outreach produces a stored **transcript** and **structured summary**.
4. Neither side can ever see the other side's private limit (brand budget ceiling, creator floor price).
5. A single failing thread (bounce, bad number, model timeout) never breaks the batch, and is visible and retryable.

### 1.5 Out of scope (v1)
Payments/escrow, calendar, e-sign/contract PDFs, platform admin, multi-currency (USD only), creator account claiming for seeded creators, brand-side listening into live calls, inbound phone calls.

---

## 2. Scope & milestones

Each milestone ends in a demoable state and gets its own implementation plan.

> **2026-10-14 re-cut:** Collabio now targets a paid production environment. M3 is the **Deal loop**, M4 is **Money** (campaign funding, deliverable approval, payouts), and M5 is **Production hardening + growth**. See `2026-10-14-collabio-m3-deal-loop-design.md`, which supersedes the M3/M4 rows below and the demo framing wherever they disagree.

| # | Milestone | Features | Demoable outcome |
|---|---|---|---|
| **M1** | Foundation + supply | Auth + role routing, onboarding, seeded marketplace, **creator package editor (voice + click)**, **voice discovery** (Gemini semantic + filters), Voice Dock (command mode) | Brand finds creators by voice and reviews packages side-by-side; creator dictates and publishes a package |
| **M2** | Brief → parallel launch | **Brief intake agent** (in-browser), per-creator delta preview, channel plan, **launch orchestrator**, personalized **outreach email**, **AI phone call** with live offer logging, **live board**, thread drawer | Launch to 10; helper's phone rings; offers stream onto the board |
| **M3** | Creator side of the table | **Creator offers board + offer desk**, **voice counter** (creator and brand), **email-reply parsing**, accept/decline, **award** loop + polite declines | Helper counters by voice or by replying to the email; brand awards; creator sees Booked |
| **M4** | Intelligence + polish | **Email→call follow-ups** (off/suggest/auto), **analytics** (both roles), marketing landing page, preflight page, demo reset, motion polish | The full chained demo |

---

## 3. The demo script (target)

Actors: **Presenter** = brand "Lumen Audio" (product: wireless earbuds). **Helper** = two creator accounts: **Arjun** (consumer tech, phone opt-in, helper's real phone) and **Priya** (tech reviews, email-first, helper's real inbox). 38 other seeded creators.

1. **Find by voice.** Presenter holds Space: *"Tech creators doing short-form reviews under two thousand dollars."* Filter chips light up (niche: tech · format: short video · price ≤ $2,000); creator cards animate in with package strips. *"Select the top ten."* Selection tray → **Review** shows packages side-by-side.
2. **Brief by voice.** *Start negotiation.* The brief agent already knows brand, product, and contact email; it asks only for deliverables, go-live date, ask, budget, flexibility (~60 s). The brief card fills field by field. Presenter: *"Make the budget twelve hundred."* Card updates; per-creator deltas recompute ("+1 video vs package · $400 under list").
3. **Launch.** Channel chips default from each creator's preference (Arjun → Call; Priya and others → Email). Follow-up policy: *Suggest*. Click **Launch to 10**. Ten cards deal onto the board; nine emails are drafted and revealed per card, then *Sent*.
4. **The phone rings.** Arjun's card shows *Calling → In call*. The helper answers on stage (speaker). The agent discloses it is an AI, states the ask (3 videos for $1,000). Helper counters *"three for thirteen hundred."* The agent checks with the backend (over ceiling) and comes back with $1,100; helper settles at $1,200. Offers appear on the card **during** the call. Call ends → transcript + structured terms + delta on the card.
5. **Switch to the creator side.** Helper's laptop (Priya): Offers board shows Lumen Audio's offer; offer desk shows *My package | Their ask*. Helper holds Space: *"I'll do three videos for eleven hundred if I get two more weeks."* Counter card fills; **Approve & send**. The brand board flips Priya's card to *Countered* live. (Alternative path shown if time permits: helper replies to the email from their phone; the reply is parsed into the same thread.)
6. **Award.** Board ranks Priya as **Best value** ($367/video vs $400/video; seed data is tuned so price dominates timeline here). Presenter opens the thread, clicks **Award**, chooses *politely decline others*. Priya's app flips to **Booked**.
7. **Close (M4).** Brand analytics: funnel for this batch, $/video vs list, time to award. Follow-up demo: a seeded email-first creator with phone opt-in shows *"No reply · Call?"* after 2 minutes.

---

## 4. Architecture

### 4.1 System diagram
```
 Brand laptop ─┐      frontend/  (Next.js 16 · React 19 · Tailwind v4 · shadcn/base-ui)
 Helper laptop ┼──►   Brand app: Discover · Brief · Board · Analytics
               │      Creator app: Offers · Offer desk · Packages · Analytics
               │      Voice Dock: Scribe realtime STT (command) · ElevenLabs Agent (conversation)
               └───────┬──────────────┬──────────────────┬────────────
               typed REST│   Realtime   │ "doorbell"        │ WebRTC (signed URL / token)
                         ▼              ▼                   ▼
   backend/ (FastAPI) ─────► Supabase: Auth · Postgres + pgvector · Realtime
     ├─► Gemini       gemini-embedding-2 · structured extraction · email drafting · intent routing
     ├─► ElevenLabs   agents · Twilio outbound call · Scribe single-use tokens · signed URLs
     ├─► Resend       outreach + notification email (send) · inbound replies (receive)
     ├◄─ ElevenLabs   server-tool webhooks (mid-call) · post-call webhook
     └◄─ Resend       email.received webhook
```

### 4.2 Architectural rules
1. **All writes go through the backend.** Business rules (outreach gating, budget ceiling, creator floor, award eligibility) live in exactly one place.
2. **Realtime is a doorbell, not the data source.** The frontend subscribes to `thread_events` INSERTs (RLS-filtered) and invalidates/refetches the affected view model from the API. Deltas and ranking are computed server-side only.
3. **No secret keys in the browser.** The browser holds only the Supabase publishable key and the user's Supabase session. ElevenLabs access is via backend-minted signed URLs (agents) and single-use tokens (Scribe).
4. **Pure core, thin adapters.** Delta engine, ranking, thread state machine, brief completeness, guardrail checks, reply-token parsing, and email quote-stripping are pure Python functions with no I/O. Gemini, ElevenLabs, Resend, and Postgres are behind adapter interfaces so the core and orchestrators are testable with fakes.
5. **The event log is the source of truth.** `thread_events` is append-only. Thread `status` and `latest_terms` are denormalized projections updated in the same transaction as the event insert.

### 4.3 Repository layout
```
Collabio/
├── frontend/                 Next.js 16 app (own package.json, components.json)
│   ├── app/(marketing)/      landing
│   ├── app/(auth)/           sign-in, sign-up, onboarding
│   ├── app/brand/            discover, briefs/[id], batches/[id], analytics
│   ├── app/creator/          offers, offers/[threadId], packages, analytics
│   ├── components/ui/        shadcn + registry components (react-bits, canvas-ui, elevenlabs)
│   ├── components/voice/     VoiceDock, CommandCapture, AgentSession, HeardChip
│   ├── components/deal/      PackageStrip, DeltaTable, TermsCard, ThreadCard, Timeline, TranscriptView
│   ├── lib/api/              generated OpenAPI types + typed fetch client
│   ├── lib/supabase/         browser/server clients, realtime hooks
│   └── tests/                vitest + playwright
├── backend/
│   ├── app/
│   │   ├── core/             pure domain: delta.py, ranking.py, thread_state.py, brief_rules.py,
│   │   │                     guardrails.py, reply_token.py, email_quotes.py
│   │   ├── schemas/          Pydantic models (shared contracts → OpenAPI → TS)
│   │   ├── modules/          discovery, packages, briefs, outreach, negotiation, offers,
│   │   │                     awards, analytics, voice, demo
│   │   ├── adapters/         gemini.py, elevenlabs.py, resend.py, db.py (asyncpg)
│   │   ├── workers/          orchestrator.py, call_watcher.py, followups.py, sweeper.py
│   │   ├── api/              FastAPI routers, auth dependency (Supabase JWT via JWKS)
│   │   └── main.py           app factory + lifespan (starts workers)
│   ├── agents/               ElevenLabs agent configs as code (prompts, tools, voice) + sync script
│   ├── supabase/             migrations/, seed/ (creators.json, embedding cache), config.toml
│   ├── templates/email/      Jinja2 outreach / counter / decline / award templates
│   ├── evals/                structurer golden set + runner
│   └── tests/
└── docs/superpowers/specs/   this document
```
The existing root-level Next.js scaffold stays untouched; it exists only to host MCP/registry configuration and is not part of the product.

### 4.4 Stack
| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind v4, shadcn (base-ui), TanStack Query, `@supabase/supabase-js` + `@supabase/ssr`, `@elevenlabs/react`, GSAP + `@gsap/react`, `openapi-typescript` + `openapi-fetch` |
| Component registries | `@react-bits`, `@canvas-ui`, ElevenLabs UI (`https://ui.elevenlabs.io/r/*.json`) |
| Backend | Python 3.12+, `uv`, FastAPI, Pydantic v2, asyncpg, `google-genai`, `elevenlabs`, `resend`, Jinja2, PyJWT, tenacity |
| Data | Supabase Postgres 17 + pgvector (HNSW, cosine), Supabase Auth (email + password), Supabase Realtime (postgres_changes) |
| AI | Gemini `gemini-embedding-2` (768-dim via MRL), Gemini `gemini-3.5-flash-lite` (switched from 3.8-flash: free-tier quota) (thinking level `low` for routing/structuring) for structuring/drafting/routing; ElevenLabs Agents (2) + `scribe_v2_realtime` |
| Hosting | Frontend → Vercel; Backend → Fly.io or Render (single instance, public HTTPS for webhooks); dev via local tunnel |

---

## 5. Voice architecture

**Principle: a conversation only where a conversation is needed; a single utterance where a command is enough; the screen always shows the state.**

### 5.1 Voice Dock
Persistent floating dock (bottom-center) in both apps. Two modes:

| Mode | Engine | Used for | Visible feedback |
|---|---|---|---|
| **Command** (hold Space / tap orb) | `scribe_v2_realtime` in the browser using a backend-minted single-use token → final transcript → `POST /voice/command` (intent router) | Discovery search, selection, navigation, package dictation, creator counter, brand counter, accept/decline, "open Priya's thread" | Live partial transcript in the dock → **"Heard: …" chip** (tap to edit/retry) → screen reacts. No spoken reply. |
| **Conversation** | ElevenLabs Agent over WebRTC via signed URL | Brief intake only | Orb states (listening / thinking / talking), captions, brief card filling live |

**Intent router** (`modules/voice`): Gemini structured output constrained to the intents valid for the current screen:

| Screen | Intents |
|---|---|
| discover | `search{semantic_query, filters}`, `select{creator_refs \| top_n}`, `clear_selection`, `open_review` |
| board / thread | `open_thread{creator_ref}`, `sort{key}`, `counter{creator_ref, terms}`, `award{creator_ref}` (opens confirm dialog only), `decline{creator_ref}` |
| offer desk | `counter{terms}`, `accept`, `decline{reason?}` |
| packages | `package_draft{fields}` |
| any | `navigate{route}`, `unclear{suggestions[]}` |

Irreversible intents (`award`, `accept`, `decline`, `counter` send) never execute directly — they open the confirmation UI pre-filled.

### 5.2 ElevenLabs agents (exactly two, distinct voices, configs versioned in `backend/agents/`)

**A. Brief Agent (in-browser)**
- Session: frontend requests `POST /briefs/{id}/voice-session` → backend returns signed URL + dynamic variables: `brand_name`, `product_name`, `product_summary`, `contact_email` (pre-filled from profile), `selected_creators_summary` (names + package one-liners), `current_brief_json` (for resume), `missing_fields`.
- Client tools (run in browser, update UI instantly, then `PATCH /briefs/{id}`):
  - `update_brief(field, value)` — field ∈ mandatory schema; value validated server-side; on validation error the tool returns the error text so the agent re-asks.
  - `show_creator(creator_ref)` — scroll/highlight a creator in the right panel.
  - `ready_to_launch()` — returns remaining missing fields or "ready"; when ready the Launch button pulses.
- Click edits on the card are sent to the agent as contextual updates so it stays in sync.
- The agent **cannot launch**. Launch is a click (sets `approved_at`).
- Brief conversation id is attached to the brief; its transcript arrives via the post-call webhook.

**B. Negotiation Agent (phone via Twilio)**
- Placed with the outbound-call API using the workspace Twilio number (`agent_phone_number_id`), with dynamic variables: `thread_id`, `creator_first_name`, `brand_name`, `product_summary`, `package_name`, `package_terms` (one-liner), `ask_videos`, `ask_price`, `go_live_by`, `flexibility`, `follow_up_context` (empty or "following up on our email from {date}").
- **The budget ceiling is never passed to the agent.**
- First message includes AI disclosure and recording consent: *"Hi {name}, this is an AI assistant calling on behalf of {brand}. This call is recorded for both parties' records — is now a good time?"*
- Server tools (webhooks to backend, authenticated by a shared-secret header, scoped by `thread_id`):
  - `check_counter(price, videos, conditions)` → `{verdict: within | over, suggested_counter_price?, talking_point}`. Backend computes against the private ceiling using a concession strategy (first concession = midpoint of ask and ceiling, never above ceiling). This is the **only** way the agent learns whether a number is acceptable.
  - `log_offer(price, videos, go_live_by, conditions, stance)` → appends a `call_offer_logged` event; the board updates mid-call.
- The agent may **agree in principle** within ceiling ("I'll confirm with Lumen Audio and you'll get a written confirmation"); binding award is always the brand's click.
- Post-call webhook → transcript stored → structurer produces final `NegotiationTerms` → thread status updated.

### 5.3 Creator-side voice
Single-utterance commands only: package dictation and counters. The counter flow: utterance → `POST /offers/{threadId}/counter/preview` → `TermsCard` with missing-field chips (a second utterance merges into the card) and a **floor warning** if price < floor → **Approve & send** (click).

### 5.4 Transcripts
Every voice path stores a transcript: brief sessions and calls via the ElevenLabs post-call webhook (keyed by `conversation_id`); command-mode utterances that change deal terms (counters, package dictation) store their transcript text on the resulting event.

---

## 6. Data model (Supabase Postgres)

### 6.1 Tables
```
profiles ─┬─< brands ─< products
 (role)   │      └─< briefs ─< batches ─< threads >─ creators ─< packages ── package_floors (1:1)
          └────────────────────────────── creators (profile_id NULL = seeded, no login)
threads ─< thread_events   (append-only; Realtime enabled)
threads ─< transcripts     (kind: email_out | email_in | call | intake)
```

| Table | Key columns |
|---|---|
| `profiles` | `id` (= auth.users.id), `role` (`brand` \| `creator`), `display_name`, `avatar_url`, `created_at` |
| `brands` | `id`, `profile_id`, `company_name`, `category`, `default_pitch`, `contact_email` |
| `products` | `id`, `brand_id`, `name`, `summary`, `key_claims text[]`, `category` |
| `creators` | `id`, `profile_id` (nullable), `handle`, `name`, `avatar_url`, `bio`, `niches text[]`, `platforms jsonb`, `region`, `languages text[]`, `followers int`, `engagement_rate numeric`, `email`, `phone` (E.164, nullable), `phone_opt_in bool`, `contact_opt_out bool`, `embedding vector(768)`, `embedding_text_hash` |
| `packages` | `id`, `creator_id`, `name`, `content_type` (`short_video` \| `long_video` \| `story` \| `live`), `niche`, `volume_count int`, `volume_basis` (`per_week` \| `per_contract`), `base_price_cents int`, `currency` ('USD'), `included text[]`, `freebies text[]`, `addons jsonb [{name, price_cents, unit}]`, `extras jsonb [{name, price_cents}]`, `slots_per_month int`, `lead_time_days int`, `preferred_channel` (`email_first` \| `phone_ok` \| `email_only`), `status` (`draft` \| `published`), `updated_at` |
| `package_floors` | `package_id` (PK), `floor_price_cents int` — **creator-only** |
| `briefs` | `id`, `brand_id`, `product_id`, `status` (`draft` \| `ready` \| `launched`), `brand_name`, `product_name`, `product_summary`, `deliverables_count int`, `deliverables_format`, `deliverable_length_s int`, `go_live_by date`, `budget_ceiling_cents int` — **brand-only**, `ask_price_cents int`, `negotiation_ask text`, `flexibility text[]` (`timeline` \| `price` \| `deliverables`), `flexibility_note`, `contact_email`, `approved_at`, `intake_conversation_id`, `creator_ids uuid[]` |
| `batches` | `id`, `brief_id`, `brand_id`, `launched_at`, `follow_up_policy` (`off` \| `suggest` \| `auto`), `follow_up_after interval`, `max_concurrency int` |
| `threads` | `id`, `batch_id`, `brand_id`, `creator_id`, `package_id` (anchor), `channel_plan` (`email` \| `call` \| `email_then_call`), `status`, `latest_terms jsonb`, `latest_terms_source` (`brand` \| `creator`), `reply_token text unique`, `next_action_at timestamptz`, `attempts int`, `last_error text`, `created_at`, `updated_at` |
| `thread_events` | `id bigserial`, `thread_id`, `batch_id`, `brand_id`, `creator_id`, `type`, `actor` (`brand` \| `brand_agent` \| `creator` \| `system`), `payload jsonb`, `terms jsonb`, `transcript_id`, `external_id text`, `created_at` — **unique (type, external_id)** for webhook idempotency |
| `transcripts` | `id`, `thread_id` (nullable), `brief_id` (nullable), `kind`, `external_id` (ElevenLabs conversation id / Resend email id / Message-ID), `subject`, `body_text`, `turns jsonb [{role, text, t}]`, `summary`, `created_at` |

Thread event `type` values: `queued`, `email_drafted`, `email_sent`, `email_bounced`, `call_placed`, `call_started`, `call_offer_logged`, `call_ended`, `email_received`, `counter_submitted` (creator in-app), `brand_counter_sent`, `accepted`, `declined`, `follow_up_suggested`, `follow_up_approved`, `awarded`, `closed_lost`, `needs_review`, `failed`, `retried`.

### 6.2 Private limits stay private
- The **creator floor** lives only in `package_floors` (readable by the owning creator). The **brand ceiling** lives only in `briefs` (readable by the owning brand).
- Neither value is ever copied into `threads`, `thread_events`, `transcripts`, email bodies, or agent dynamic variables.
- The backend reads both with privileged access: the floor for the creator's counter warning, the ceiling for `check_counter` and brand-counter validation.

### 6.3 Row-level security
| Table | Read | Write |
|---|---|---|
| `profiles` | self | self (via backend) |
| `creators` (holds contact email/phone) | owning creator only — brands get creator data only through the API, which never returns contact fields | owning creator via backend |
| `packages` (published) | any authenticated user | owning creator via backend |
| `package_floors` | owning creator | owning creator via backend |
| `brands`, `products`, `briefs`, `batches` | owning brand | via backend |
| `threads`, `thread_events`, `transcripts` | the thread's brand **or** creator | backend only |

The backend connects with privileged credentials and therefore bypasses RLS; **every endpoint enforces ownership explicitly in code**, and tests cover both layers.

### 6.4 Shared schemas (Pydantic → OpenAPI → TypeScript)
- **`DealBrief`** — the mandatory variables with validators (see §7.3).
- **`NegotiationTerms`** — `videos`, `format`, `price_cents`, `go_live_by`, `conditions[]`, `addons[]`, `stance` (`offer | counter | accept | decline | question | no_commitment`), `source` (`call | email | in_app`), `confidence` (0–1), `open_questions[]`.
- **`PackageDelta`** — computed view (§7.1).
- **`BestValue`** — computed ranking with reason chips (§7.2).

### 6.5 Search
- One embedding per creator from `bio + niches + published package one-liners`, `gemini-embedding-2` at 768 dimensions with the task-instruction format recommended for retrieval (document vs query).
- Re-embedded on package publish; `embedding_text_hash` skips unchanged text.
- SQL function `match_creators(query_embedding, max_price_cents, content_types, niches, region, min_followers, limit)`: hard filters on joined published packages, ordered by cosine distance; HNSW index.

### 6.6 Analytics views
- `v_batch_funnel` — per batch: contacted, delivered, replied, countered, accepted, awarded.
- `v_brand_kpis` — avg awarded $/video vs list $/video, median launch→award time, reply rate by channel.
- `v_creator_kpis` — inbound offers per week, accept rate, avg deal value vs package list price.

### 6.7 Seed data
- ~40 creators across 6 niches (consumer tech, beauty, fitness, food, gaming, B2B SaaS) with 1–3 packages each, deterministic JSON in `backend/supabase/seed/`.
- Embedding cache file keyed by text hash so **Reset demo** reseeds in seconds without calling Gemini.
- Demo accounts: brand **Lumen Audio** (presenter), creators **Arjun** (phone opt-in, helper's phone) and **Priya** (email-first, helper's email), configured from env.
- Historical batches/threads/events for analytics so charts are not empty.

---

## 7. Domain logic (pure core)

### 7.1 Delta engine — `core/delta.py`
Inputs: package, brief ask, latest terms (optional).
- `listed_price_for(videos)`: if `videos ≤ volume_count` → `base_price`; otherwise `base_price + (videos − volume_count) × extra_video_addon_price` when the package has an add-on with `unit = "video"`; otherwise extrapolate at `base_price / volume_count` per video and mark the result `estimated`.
- Output rows: videos (listed / ask / latest), price (listed-for-ask / ask / latest), $/video, timeline (lead time vs go-live), requested add-ons.
- Headline string, e.g. *"+1 video vs package · $400 under list (−29%)"*.
- Flags: `below_base_price` (ask price < package base price — rule 7.3 of the brief, shown before send), `lead_time_conflict` (go-live sooner than lead time), `estimated`.

### 7.2 Best-value ranking — `core/ranking.py`
- Eligible: thread has creator-sourced terms (`countered` or `accepted`), price ≤ ceiling, videos ≥ brief deliverables.
- Score = 0.5 × normalized $/video (lower is better) + 0.25 × timeline fit + 0.25 × audience fit (semantic similarity to brief + engagement). Ties broken by engagement.
- Output includes reason chips (e.g. "lowest $/video", "meets go-live date"). Ineligible threads are shown with the reason (e.g. "over budget").

### 7.3 Brief completeness — `core/brief_rules.py`
Required: `brand_name`, `product_name`, `product_summary` (≤ 200 chars), `deliverables_count ≥ 1` + `deliverables_format`, `go_live_by` (future date), `budget_ceiling_cents > 0`, `ask_price_cents > 0` and `≤ budget_ceiling_cents`, `negotiation_ask`, `flexibility` (≥ 1 value or explicit `none`), `contact_email` (valid). `approved_at` is set only by the Launch click. Launch is rejected unless complete.

### 7.4 Thread state machine — `core/thread_state.py`
```
queued ─► drafting ─► sent ─► awaiting_reply ─┬─► countered ─┬─► awarded
   │                                          ├─► accepted ──┘     (others ─► closed_lost)
   └─► calling ─► in_call ─► (call_ended) ────┤
                                              ├─► declined
awaiting_reply ─► follow_up_suggested ─► calling      (policy: suggest → click; auto → immediate)
countered ─► awaiting_reply                           (brand counter sent)
awaiting_reply ─► no_response                         (expiry)
any non-terminal ─► needs_review                      (structurer confidence < 0.6 or unknown sender)
any non-terminal ─► failed ─► queued                  (retry)
```
- Transitions are validated by a pure function; the database update is a single conditional `UPDATE … WHERE status = :expected` so double clicks and restarts cannot double-send or double-call.
- `awarded` is allowed only from `countered` or `accepted` (the brand accepts the creator's latest terms → both sides see **Booked**).

### 7.5 Guardrails — `core/guardrails.py`
- `check_counter(ceiling, ask, offered)` → verdict + concession suggestion (never above ceiling).
- Creator counter: `below_floor` warning when price < floor; sending below floor requires an explicit second confirmation click.
- Brand counter: rejected above ceiling.
- Channel policy: `call` and follow-up calls require `phone_opt_in` and a phone; `contact_opt_out` creators are excluded at launch.

### 7.6 Email reply helpers — `core/reply_token.py`, `core/email_quotes.py`
- Reply-to address `t-{reply_token}@{RESEND_INBOUND_DOMAIN}`; parser extracts the token. Fallback matching on `In-Reply-To` against stored outbound Message-IDs.
- Quote stripping handles `On … wrote:`, `>`-prefixed lines, Gmail/Outlook separators, and signatures.

---

## 8. Pipelines

### 8.1 Launch orchestration (M2)
1. `POST /briefs/{id}/launch {channels: {creator_id: channel_plan}, follow_up_policy}` validates completeness, sets `approved_at`, creates the batch and N threads (`queued`) in one transaction and returns immediately.
2. Orchestrator claims queued threads with `SELECT … FOR UPDATE SKIP LOCKED` (safe across restarts and multiple instances) under a concurrency limit (default 5).
3. Per thread, by channel plan:
   - **Email:** Gemini drafts the personalized paragraphs (structured output: subject, opener, ask paragraph, rationale) from the brief + creator profile + package + delta → Jinja template adds the package-vs-ask table, a **"Review & respond in Collabio"** link (`/creator/offers/{threadId}`), the reply-to address, AI-disclosure footer, and an unsubscribe link → Resend send with idempotency key `thread:{id}:email:{n}` → `email_sent`.
   - **Call:** outbound call with dynamic variables → `call_placed` (stores the returned `conversation_id`). ElevenLabs only notifies us after the call ends, so a **call watcher** polls the conversation status every 2 s while the call is live: `in-progress` → `call_started`; ended without a connected conversation → `failed` ("no answer") with Retry. `call_offer_logged` arrives via the `log_offer` server tool mid-call; `call_ended` + transcript arrive via the post-call webhook.
4. Each thread is isolated: exceptions produce a `failed` event with a human-readable reason and a Retry action.
5. The board's "email being written" effect is a client-side reveal of the **real** drafted text once the `email_drafted` event arrives.

### 8.2 Reply ingestion — one structurer for every channel (M2–M3)
| Source | Entry point | Structurer input |
|---|---|---|
| Phone call | ElevenLabs post-call webhook (HMAC verified) | Full transcript + `log_offer` events |
| Email reply | Resend `email.received` webhook (Svix verified) → fetch body → strip quotes → verify sender matches creator email | Reply body + prior thread context |
| In-app counter | `POST /offers/{threadId}/counter` | Already-structured terms (from preview) + utterance |

The structurer (Gemini structured output → `NegotiationTerms`) gets the brief, package, and prior terms as context. Confidence < 0.6 or unknown sender → `needs_review`.

### 8.3 Counters & award (M3)
- **Creator counter:** preview → TermsCard (floor warning) → Approve & send → `counter_submitted` event + notification email to the brand contact.
- **Brand counter:** command-mode utterance on the thread → preview → confirm → email rendered to the creator (`brand_counter_sent`, thread → `awaiting_reply`).
- **Accept / decline (creator):** one click; decline offers an optional spoken reason rendered into a polite email.
- **Award (brand):** confirmation dialog shows agreed terms; options: *politely decline others* (Gemini-personalized decline emails, threads → `closed_lost`) or *leave others open*. Awarded thread → both sides **Booked**.

### 8.4 Follow-ups (M4)
- Background sweep every 15 s selects threads in `awaiting_reply` with `channel_plan ∈ {email, email_then_call}`, no reply after `follow_up_after`, creator `phone_opt_in = true`.
- Policy **suggest** → `follow_up_suggested` (card shows *"No reply · Call {name}?"*, one click → call). Policy **auto** → call placed immediately with `follow_up_context`.
- `follow_up_after` defaults: 3 days; `DEMO_MODE` → 2 minutes.

---

## 9. API surface (`/api/v1`, all JSON, Supabase JWT bearer unless noted)

| Area | Endpoints |
|---|---|
| Me | `GET /me`, `POST /onboarding` |
| Voice | `POST /voice/scribe-token`, `POST /voice/command` |
| Discovery | `POST /discovery/search`, `GET /creators/{id}` |
| Packages (creator) | `GET /me/packages`, `POST /me/packages/draft-from-speech`, `POST /me/packages`, `PATCH /me/packages/{id}`, `POST /me/packages/{id}/publish`, `PUT /me/packages/{id}/floor` |
| Briefs | `POST /briefs`, `GET /briefs/{id}`, `PATCH /briefs/{id}`, `GET /briefs/{id}/preview`, `POST /briefs/{id}/voice-session`, `POST /briefs/{id}/launch` |
| Board | `GET /batches`, `GET /batches/{id}`, `GET /threads/{id}`, `POST /threads/{id}/counter/preview`, `POST /threads/{id}/counter`, `POST /threads/{id}/award`, `POST /threads/{id}/decline`, `POST /threads/{id}/retry`, `POST /threads/{id}/follow-up/approve`, `POST /threads/{id}/browser-call` |
| Offers (creator) | `GET /offers`, `GET /offers/{threadId}`, `POST /offers/{threadId}/counter/preview`, `POST /offers/{threadId}/counter`, `POST /offers/{threadId}/accept`, `POST /offers/{threadId}/decline`, `POST /offers/{threadId}/join-call` |
| Analytics | `GET /analytics/brand`, `GET /analytics/creator` |
| Webhooks (no JWT; signature/secret) | `POST /webhooks/elevenlabs/post-call`, `POST /webhooks/elevenlabs/tools/check-counter`, `POST /webhooks/elevenlabs/tools/log-offer`, `POST /webhooks/resend/inbound` |
| Demo (`DEMO_MODE` + admin token) | `GET /demo/preflight`, `POST /demo/reset` |

`GET /batches/{id}` and `GET /offers/{threadId}` return complete **view models** (threads + latest terms + delta + ranking + recent events) so the frontend renders without client-side business logic.

---

## 10. Screens & flows

**Shell:** one sign-in, onboarding chooses role ("I sell products" / "I create content"), separate route trees `/brand/*` and `/creator/*` with role guards. Slim left rail; Voice Dock fixed bottom-center.

### Brand
- **Discover (M1):** filter chips (niche, format, price band, volume, region) — voice search sets chips visibly; creator cards with stats + **package strip**; selection tray → **Review** side-by-side package table (price, $/video, volume, lead time, channel).
- **Brief (M2):** left = brief card (filled / missing-pulsing / just-changed-flash); right = selected creators with live delta preview, channel chip (Call disabled without opt-in), follow-up policy toggle; `below_base_price` warnings; **Launch to N** locked until complete.
- **Board (M2–M3):** KPI strip (contacted, replied, countered, best $/video, time since launch); thread cards (status pill, latest terms, mini delta, last event line; email cards reveal the drafted email; call cards show an in-call indicator and offers logged live; follow-up cards show *Call?*); **Best value** badge; thread drawer with cross-channel timeline, transcript viewer, terms, delta, actions (Counter by voice, Award, Decline, Retry, Take call in browser).
- **Analytics (M4):** funnel, $/video vs list, time to award, batches table.

### Creator
- **Offers (M3):** decision board of inbound brand offers, sortable by fit / revenue / timeline; each row shows closest package, delta chips, total value, status.
- **Offer desk (M3):** **My package | Their ask | Latest** columns with changed rows highlighted; timeline; Accept / Decline / **Counter by voice** → TermsCard → Approve & send; Booked state after award.
- **Packages (M1):** package cards; **New package** = say it → structured draft card → adjust with chips/steppers → Publish (re-embed); floor price as a separate locked field.
- **Analytics (M4):** inbound volume, accept rate, deal value vs list.

### Marketing (M4)
One-page landing with GSAP ScrollTrigger storytelling and Register / Sign in CTAs.

---

## 11. Error handling & demo resilience
- **Per-thread isolation** with visible `failed` reasons (bounce, invalid number, provider error, model timeout) and Retry.
- **Exactly-once effects:** conditional status updates; Resend idempotency keys; webhook idempotency via `unique(type, external_id)`; webhook signature verification (ElevenLabs HMAC, Resend/Svix); server tools require a shared-secret header and a thread in `in_call`.
- **Retries:** tenacity exponential backoff (max 3) on Gemini and Resend calls; no automatic retry of phone calls (manual Retry only).
- **Low confidence:** structurer confidence < 0.6 → `needs_review` with transcript link; numbers are never invented.
- **Voice fallbacks:** mic denied → Dock switches to a text input; agent disconnect → brief is already persisted, **Resume** reconnects with current state; STT failure → text input.
- **Workers:** in-process asyncio workers started in the FastAPI lifespan; job state in Postgres; startup sweep resumes `queued`/stuck threads.
- **Cost caps:** per-brand limits on calls per day and call minutes; launch concurrency cap.
- **Demo kit:** `DEMO_MODE` (2-minute follow-ups), **Reset demo** (wipe + reseed in seconds), **Preflight page** (Gemini, ElevenLabs agents + phone number, Resend domain + inbound, Supabase, webhook reachability — green/red), **Take call in browser** fallback: the brand clicks *Switch to browser call* on the thread → the creator's offer desk (helper signed in as that creator) shows **Join call** → the creator's browser starts the same Negotiation Agent over WebRTC with a signed URL and the same dynamic variables, scoped to that thread → same server tools, same post-call webhook, same board updates.

---

## 12. Security & compliance
- Secrets only in backend env; browser gets the publishable key + short-lived ElevenLabs credentials.
- Supabase JWT verified in FastAPI via JWKS; role loaded from `profiles`.
- RLS on every table plus explicit ownership checks in every endpoint.
- AI disclosure on calls (first message) and emails (footer); recording-consent statement at call start.
- Unsubscribe link sets `contact_opt_out`; opted-out creators are excluded from launch.
- Inbound email sender must match the thread's creator email, else `needs_review`.
- No outreach without complete brief + Launch click (`approved_at`).

---

## 13. Testing strategy
- **Backend (pytest), test-first for the pure core:** delta engine, ranking, state machine transitions, brief completeness, guardrails (ceiling/floor/concession), reply-token parsing, quote stripping.
- **Orchestrator tests with fake adapters:** launch 10 with one failure → 9 succeed, failure visible; restart mid-launch resumes without duplicates.
- **Webhook tests** with signed sample payloads (valid, invalid signature, duplicate delivery).
- **RLS tests on local Supabase** (CLI + Docker; fallback: dedicated test project): brand cannot read floors; creator cannot read ceilings; brand A cannot read brand B's threads; creator sees only their threads.
- **Structurer eval set** (`backend/evals/`): ~20 call/email/in-app snippets with expected `NegotiationTerms`; run on demand against live Gemini (not in CI).
- **Frontend:** Vitest + Testing Library for Voice Dock state machine and brief card state; **Playwright smoke** for the chained flow with voice replaced by typed commands; `tsc` + ESLint.

---

## 14. Visual system
- **Concept: calm deal room.** Information-dense but readable. **Motion only signals state change** (new offer, status change, re-rank, best value); no ambient animation on work screens; decorative backgrounds only on landing and empty states.
- **Typography:** distinctive display serif for headings; clean sans for UI; **monospace with tabular numerals for every price and count**.
- **Color:** warm neutral base; one signature accent reserved for voice (Orb, Dock, "Heard" chip); semantic gain/loss colors for deltas; status palette for thread pills. Light and dark themes (WCAG AA).
- **Component sourcing:**
  - shadcn/base-ui: drawer, dialog, tabs, table, toggle groups, tooltip, command.
  - ElevenLabs UI: Orb, live waveform, voice button, transcript/conversation components.
  - react-bits: CountUp (KPIs, prices), BlurText/SplitText (headings), AnimatedList (event feed), ShinyText ("Best value"), SpotlightCard (creator cards), Aurora/Silk (landing + empty states only).
  - canvas-ui (page-level WebGL effects, e.g. `liquid-react`, `glass-object-react`): marketing landing hero and sign-in backdrop only — never on work screens. The Voice Dock's glass look is plain CSS (`backdrop-filter`).
  - GSAP: Flip for board re-rank/status moves; timeline for the launch "deal" of 10 cards; ScrollTrigger on landing; all honor `prefers-reduced-motion`.
- **Accessibility:** every voice action has a click equivalent; captions for all agent speech; hold-Space push-to-talk; visible focus states.

---

## 15. Prerequisites & configuration

| # | Prerequisite | Needed by |
|---|---|---|
| 1 | Gemini API key | M1 |
| 2 | New Supabase project `collabio` (free tier allows it alongside the active `Portfolio` project) | M1 |
| 3 | ElevenLabs API key (workspace already has Twilio number `+1 256-988-7711`, outbound-capable) | M1 (Scribe), M2 (agents) |
| 4 | Domain verified in Resend for sending to real inboxes; receiving via a `*.resend.app` address or a subdomain MX record | M2 (send), M3 (receive) |
| 5 | Helper's phone number and email | M2 |
| 6 | Twilio geo-permissions for the helper's country if not US; test call at least a day before the demo | M2 |
| 7 | ElevenLabs workspace post-call webhook URL + HMAC secret configured | M2 |
| 8 | Vercel + Fly.io/Render accounts | M2 (webhooks need public HTTPS) |
| 9 | Docker Desktop for local Supabase (optional; else a test project) | M1 tests |

Backend env (names fixed now): `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_DB_URL`, `SUPABASE_JWKS_URL`, `GEMINI_API_KEY`, `GEMINI_TEXT_MODEL`, `GEMINI_EMBED_MODEL`, `ELEVENLABS_API_KEY`, `ELEVENLABS_BRIEF_AGENT_ID`, `ELEVENLABS_NEGOTIATION_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID`, `ELEVENLABS_WEBHOOK_SECRET`, `ELEVENLABS_TOOL_SECRET`, `RESEND_API_KEY`, `RESEND_FROM`, `RESEND_INBOUND_DOMAIN`, `RESEND_WEBHOOK_SECRET`, `PUBLIC_BACKEND_URL`, `PUBLIC_FRONTEND_URL`, `DEMO_MODE`, `DEMO_ADMIN_TOKEN`, `DEMO_BRAND_EMAIL`, `DEMO_PASSWORD`, `DEMO_HELPER_PHONE`, `DEMO_HELPER_EMAIL`.

Frontend env: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_API_URL`.

The existing Twilio number is currently assigned to the "Support agent" for inbound calls. Outbound calls specify the agent per call, so no reassignment is required.

---

## 16. Open decisions from the business brief — resolved for v1
| # | Question | v1 decision |
|---|---|---|
| 1 | Max parallel outreach | 10 creators per batch; concurrency 5 |
| 2 | Owner approves each counter-send? | Brand counters are always confirmed by click; the phone agent may agree in principle within ceiling, but binding award is a click |
| 3 | Public marketplace vs invite-only | Public to authenticated brands |
| 4 | Single vs separate agents | Two agents (brief, negotiation) with distinct voices; everything else is command mode |
| 5 | Email provider / reply parsing | Resend for send and receive; replies parsed into threads |
| 6 | Currency | USD only |
| 7 | Dispute flow | Out of scope; immutable event log + transcripts retained |

---

## 17. Risks
| Risk | Mitigation |
|---|---|
| Live phone call fails on stage (signal, geo-permissions) | Preflight test call; **Take call in browser** fallback |
| Model latency makes voice feel slow | Live partial transcripts; optimistic "thinking" states; parallel embedding + intent parsing for search |
| Email lands in spam / slow delivery | Verified domain with SPF/DKIM; the in-app link and in-app counter don't depend on email delivery |
| Structurer misreads terms | Confidence gate → `needs_review`; eval set; terms always shown with transcript source |
| Free-tier limits (Supabase pausing, ElevenLabs minutes) | Keep project active before demo; per-brand cost caps; preflight checks quotas |
| Scope (4 milestones) | Each milestone independently demoable; M2 alone delivers the core story |

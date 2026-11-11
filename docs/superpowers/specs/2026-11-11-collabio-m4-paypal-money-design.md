# Collabio M4: Money on PayPal with a Claude settlement agent (design)

- **Status**: approved in brainstorming on Nov 11, 2026. The written spec is awaiting review.
- **Branch**: `hackathon/paypal-money`. It is swapped to `main` after the hackathon.
- **Target**: PayPal AI Hackathon (Devpost). Hard deadline **Nov 12, 2026, 12:00 PM PST = Nov 13, 01:30 IST**. Internal deadline: Devpost **submitted by Nov 12, 22:00 IST** and the video public by 20:00 IST.
- **Parent specs**: `2026-10-09-collabio-design.md` (M1/M2) and `2026-10-14-collabio-m3-deal-loop-design.md` (M3). This spec adds M4 and a hackathon mode, and changes nothing about M1–M3 behavior except where it says so.

---

## 1. Intent

### 1.1 Outcome
Win at the PayPal AI Hackathon:
- a Grand Prize, or the Best Use of Agentic Commerce or Best Use of PayPal + AI Honorable Mentions;
- **plus the AG Grid sponsor prize**, with Render and APIMatic also eligible.

Judges score 1 to 5 on five equally weighted criteria:
- **Technological Implementation**: a non-trivial use of PayPal and AI.
- **Design**: a complete product, not a proof of concept.
- **Impact**: a real problem for a real audience.
- **Innovation**.
- **Presentation**: a video under 3 minutes.

Stage One is pass/fail: PayPal and AI must be *meaningfully* used, the build must be runnable, the repo public with an open source license, and the YouTube video public.

### 1.2 Problem
Collabio already gets a brand and a creator to an awarded deal with milestones (M3), but money never moves.

Founder interviews (founder-intel corpus) show that brands pay creators by hand, against deal terms such as view clauses, CPM with caps and bonus tiers:
- 32 of 292 featured founders pay influencers.
- Creators chase payments, and brands overpay or underpay.

M3's own money model reads: *"the brand pre-funds a campaign budget; the platform holds it; creators are paid from it as each deliverable is approved; refund of unused budget."*

### 1.3 What M4 delivers
1. A brand **funds an awarded deal with PayPal Checkout**: the milestones plus the maximum performance bonus.
2. A creator **submits proof** per milestone: the post URL, the caption or script, and an analytics screenshot.
3. A **Claude settlement agent**:
   - verifies the brief and disclosure;
   - reads the view count from the screenshot with vision;
   - asks the deterministic payout engine what is owed;
   - **pays the creator itself with PayPal Payouts**, unless the amount exceeds the brand's auto-approve limit, in which case the payout is queued for the brand's approval.
4. **Closing the deal refunds the unspent budget** through PayPal.
5. An **AG Studio money dashboard** for the brand, with a Claude-powered "Ask Collabio" agent.
6. A **hackathon mode** that makes the app clean and safe for public judging.

### 1.4 Success criteria
1. On the hosted URL, a judge can do the following with no keys and no sign-up:
   1. enter as the brand;
   2. fund a deal through sandbox PayPal Checkout (using the buyer login in the README);
   3. switch to the creator and submit proof;
   4. watch Claude verify and pay;
   5. see the payout succeed;
   6. close the deal and see the refund.
2. Every money movement is a real PayPal sandbox API call, recorded in an append-only ledger and reconciled. The total paid out plus the total refunded never exceeds the captured amount.
3. The model can never move more money than the deterministic engine allows, nor more than the brand's limit without approval. These rules are enforced server-side, not by prompt.
4. The demo survives until Dec 21, 2026:
   - PayPal tokens refresh automatically;
   - AI usage is capped;
   - Supabase is kept awake by a cron job;
   - a "Reset demo" button restores the seed data.
5. There are no third-party trademarks on screen: fictional names, and generated analytics screenshots.

### 1.5 Out of scope (hackathon)
- Indian payment rails, and freemium billing for voice. Both are **future work after the hackathon**.
- Live PayPal, real social-platform APIs, disputes, a platform fee, multi-currency (USD only).
- Card fields: sandbox returns `PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING`, so only PayPal wallet checkout is used.
- Vaulting: refused for sandbox platform apps.
- PayPal's hosted MCP server, which has been broken since Oct 29 (issue #119).

---

## 2. Verified platform facts (smoke test, Nov 11, 2026)

These were tested with US sandbox accounts (one business, two personal) and an app linked to the US business account:
- The token lasts 9 h and carries Payouts and Invoicing scopes.
- Orders v2 with the PayPal wallet: create, approve in the browser, then capture. **Works.**
- A partial refund of a capture: **works**.
- **Payouts** to the second personal account: SUCCESS (fee $0.25).
- Card payment_source: **fails** (see above).

---

## 3. Hackathon mode

There is one backend flag, `HACKATHON_MODE=1`, and one frontend flag, `NEXT_PUBLIC_HACKATHON_MODE=1`. Everything below is **flagged, not deleted**.

| Area | Behavior in hackathon mode |
|---|---|
| Landing `/` | Hero section, a "how money moves" strip, and two buttons: **Enter as Lumen Audio (brand)** and **Enter as Priya (creator)**, plus a **Judge guide** drawer containing the PayPal sandbox buyer login. |
| Persona sign-in | A Next.js route handler (`/api/demo-login?as=brand\|creator`) signs in server-side with the existing demo accounts (`DEMO_BRAND_EMAIL`, `DEMO_HELPER_EMAIL`, `DEMO_PASSWORD`) and sets the Supabase session cookies. The password never reaches the browser. |
| Sign-up, onboarding, sign-in pages | Redirect to `/`. A persona switcher in the app header replaces sign-out. |
| Phone calls | Outbound negotiation calls and the "Try it yourself" call are off. Their buttons show "Calls are off in the public demo." Outreach goes by email and in-app only. The backend rejects call-start endpoints with 403 `disabled_in_demo`. |
| Browser voice (ElevenLabs speech-to-text and voice briefs) | Stays on, with a per-user daily session cap. Typing is always available. |
| AI caps | A `usage_counters` table limits each user per day: settlement runs ≤ 30, dashboard agent messages ≤ 40, bonus-term previews ≤ 30, voice sessions ≤ 15. Hitting a cap returns 429 `demo_cap` with friendly copy. |
| Reset demo | The **Reset demo** item in the persona switcher calls `POST /api/v1/demo/reset`, which reseeds the demo deals and money rows (§9). It is limited to 1 per minute. |

---

## 4. User flows

### 4.1 Brand: fund a deal (deal page `/brand/deals/[id]`)
1. A booked deal shows the new **Money** panel with the state "Not funded".
2. **Performance bonus (optional)**: the brand types plain English, e.g. "$2 per 1K views after 200K, up to $500 per video, plus $300 if a video hits 1M".
   - **Preview** sends the text to Claude (Haiku), which returns structured `BonusTerms`.
   - The engine renders worked examples (views 100K / 500K / 1M → bonus per video), the maximum bonus per video, and the **funding total**.
   - The brand can edit the structured fields directly.
   - Bonus terms can only be saved before funding.
   - Bonuses only *add* to the creator's agreed pay, so no creator re-confirmation is needed. This is consistent with M3 §4.4.1.
3. **Auto-approve limit**: a per-brand setting shown inline, default **$300**. Payouts above it need a click.
4. **Fund with PayPal**: PayPal JS SDK v6 buttons. If v6 integration fails during the build, fall back to redirecting to the order's `payer-action` link and a return route. Then:
   - the backend creates the order and the buyer approves;
   - the backend captures and verifies the amount and `custom_id`;
   - the deal becomes **funded**, the milestones become **funded**, and the creator is notified (existing outbox email plus a realtime event).
   - The funding total is the sum of the milestone amounts plus `videos × max_bonus_per_video`.

### 4.2 Creator: submit proof (`/creator/deals/[id]`)
1. The existing "Payment schedule" now shows each milestone's live status and a **Submit proof** button. The button is enabled while the milestone is funded, `needs_changes`, or paid (more views can unlock more bonus).
2. The dialog takes the post URL, the caption or script text, the **views the creator claims**, and an analytics screenshot (PNG/JPG ≤ 5 MB). The screenshot is stored in a private Supabase Storage bucket, `proofs`.
3. On submit, a settlement run starts (§6). The creator sees a live verdict card, e.g. "Brief ✓ · Disclosure ✓ · 812,400 views read from screenshot → $1,124 owed · Paying via PayPal…", followed by the payout status (Pending → Paid), and a running "Earned on this deal" total.

### 4.3 Brand: approve, monitor, close
- **Approval card** (on the deal page, plus a badge in the nav): shows the agent's verdict, its evidence (the screenshot thumbnail, the views read, the checks), and the computed amount, with **Approve payout** and **Reject** (reason required, sent to the creator as `needs_changes`).
- **Ledger**: every money event in time order, e.g. funded $X → payout $Y (Pending → Success) → refund $Z, each with its PayPal ID.
- **Close & refund**: available once every milestone is paid, or after `go_live_by` + 7 days. It refunds `captured − paid_or_pending − refunded` to the brand through a PayPal refund of the capture. The deal becomes **completed**, and no further payouts are possible.

### 4.4 Brand: money dashboard (`/brand/money`)
An AG Studio report over the brand's money data:
- KPI tiles: funded, paid, pending approval, refunded;
- spend vs. budget per deal;
- effective cost per 1K views per creator;
- payouts over time;
- a bonus-vs-base split.

An **"Ask Collabio"** assistant (an AG Studio agent running on Claude) answers questions and builds widgets, e.g. "show cost per 1K views by creator this month".

---

## 5. Payout engine (`backend/app/core/settlement.py`; pure, test-first)

All amounts are integer cents. All rounding is floor.

```
BonusTerms:
  cpm: {rate_cents_per_1k: int ≥ 1, starts_after_views: int ≥ 0, cap_cents: int ≥ 1} | None
  tiers: list[{views: int ≥ 1, bonus_cents: int ≥ 1}]   # sorted by views ascending, unique views, ≤ 5 tiers

bonus_for(views, terms) =
    (min(cap, floor(max(0, views − starts_after) × rate / 1000)) if cpm else 0)
  + sum(t.bonus_cents for t in tiers if views ≥ t.views)

max_bonus_per_video(terms) = (cpm.cap_cents if cpm else 0) + sum(t.bonus_cents for t in tiers)
funding_total(deal, terms) = sum(milestone.amount_cents) + deal.videos × max_bonus_per_video(terms)

owed_for_milestone(m) = (m.amount_cents if m.verified else 0) + bonus_for(m.best_verified_views, terms)
   # best_verified_views is monotonic: max views from verified submissions
delta(m) = owed_for_milestone(m) − sum(payouts for m with status in {approved, sent, success, awaiting_approval})
payable(m) = clamp(delta(m), 0, available)
   where available = captured − sum(all non-failed, non-rejected payouts) − refunded
```

Validation (exposed as error codes):
- `terms_invalid`: the tiers are unsorted or duplicated, or there are more than 5.
- A non-positive amount.
- `funding_too_large` if `funding_total > $10,000`. This is a demo guard.

Tested exhaustively and table-driven:
- no terms;
- CPM below, at, and above the start;
- the cap;
- the tier edges;
- monotonic views (a lower resubmission pays nothing);
- re-submission deltas;
- the `available` clamp;
- the refund amount.

---

## 6. Claude settlement agent (`backend/app/agents/settlement_agent.py`)

- **Trigger**: one run per submission, started from proof submission. It runs on Render Workflows when configured (§8), otherwise as an in-process background task. A run is idempotent per submission, enforced by `unique(submission_id)` on runs.
- **Model**: `claude-sonnet-5-5`, which handles vision for the screenshot. It is a tool-use loop of at most 8 steps, with a system prompt containing the brief's talking points, the disclosure requirement, the deal terms, and the rules.
- **Tools** are server-implemented; the model never supplies money amounts:

| Tool | What it does |
|---|---|
| `get_deal_context()` | Returns the brief (talking points, required disclosure tag, product), the agreed terms, the bonus terms, the milestone and the submission. |
| `record_verification(brief_ok, missing_points[], disclosure_ok, views, view_confidence: high\|medium\|low, summary)` | Persists the verdict on the submission. If `views` is lower than the best previously verified views, the engine ignores it. |
| `quote_payout()` | Returns the engine's `delta`, `payable`, and the breakdown (base, CPM, tiers, already paid). |
| `pay_creator(reason)` | The server re-quotes. If `payable == 0`, nothing happens. Otherwise, it auto-pays only if `payable ≤ auto_approve_limit` **and** `view_confidence ≠ low` **and** the views read are within 5% of `claimed_views` **and** `brief_ok && disclosure_ok`. In every other case, the payout row is created as `awaiting_approval`. The tool returns the outcome. |
| `request_changes(message)` | Marks the submission `needs_changes` with the agent's message to the creator; no money moves. |

- **Guardrails**:
  - Server-side checks are the only path to money.
  - Every tool call and result is stored in `settlement_runs.transcript` (JSON) and shown, summarized, in the UI ("Why this amount?").
  - A timeout or model error leaves the submission `submitted` with a "Retry verification" action.
- **Bonus-term parsing** (`agents/terms_parser.py`): `claude-haiku-5-5` with structured output. The JSON is validated into `BonusTerms`, and if it fails validation, the endpoint returns 422 with the model's question for the brand.

---

## 7. Data and API

### 7.1 Migration `…_m4_money.sql`
- `deals.status` check gains `funded` and `completed`. The immutability trigger still only allows `status` to change.
- `deal_milestones.status` check gains `funded`, `submitted`, `needs_changes`, `verified`, `paid`.
- `brands.auto_approve_limit_cents int not null default 30000 check (between 0 and 1000000)`.
- `creators.payout_email text`, used as the PayPal Payouts receiver. The seed sets Priya's to the sandbox receiver account.
- New tables. All have RLS on; "read" means the deal's brand owner or creator owner, and writes are backend only, matching M3 §3.3:

| Table | Key columns |
|---|---|
| `deal_bonus_terms` | `deal_id pk`, `source_text`, `terms jsonb`, `max_bonus_per_video_cents`, `created_at` |
| `deal_funding` | `deal_id pk`, `paypal_order_id unique`, `capture_id unique`, `amount_cents`, `status (created\|captured\|failed)`, `refunded_cents default 0`, `captured_at` |
| `milestone_submissions` | `id`, `milestone_id`, `post_url`, `caption`, `claimed_views int`, `screenshot_path`, `status (submitted\|verified\|needs_changes\|failed)`, `brief_ok`, `disclosure_ok`, `missing_points text[]`, `views int`, `view_confidence`, `agent_summary`, `created_at` |
| `settlement_runs` | `id`, `submission_id unique`, `status (running\|done\|error)`, `transcript jsonb`, `started_at`, `finished_at` |
| `payouts` | `id`, `milestone_id`, `submission_id`, `amount_cents`, `breakdown jsonb`, `status (awaiting_approval\|approved\|sent\|success\|failed\|rejected)`, `paypal_batch_id`, `paypal_item_id`, `sender_batch_id unique`, `decided_by`, `reject_reason`, `created_at`, `updated_at` |
| `money_events` | `id bigserial`, `deal_id`, `kind (funded\|payout_queued\|payout_sent\|payout_succeeded\|payout_failed\|payout_rejected\|refunded)`, `amount_cents`, `paypal_ref`, `payload jsonb`, `created_at`. Append-only: a trigger rejects UPDATE and DELETE except during demo reset. |
| `usage_counters` | `user_id`, `day`, `kind`, `count`, `pk(user_id, day, kind)` |

### 7.2 PayPal adapter (`backend/app/adapters/paypal.py`)
- An `httpx.AsyncClient` against `https://api-m.sandbox.paypal.com`.
- The token comes from the client ID and secret, is cached until 5 minutes before expiry, and is refreshed once on a 401.
- `PayPal-Request-Id` on every POST, which makes it idempotent.
- Retries on 429 and 5xx through tenacity (already a dependency).
- Methods: `create_order(amount_cents, custom_id, invoice_id, description)`, `get_order`, `capture_order`, `refund_capture(capture_id, amount_cents, note)`, `create_payout(sender_batch_id, receiver_email, amount_cents, note)`, `get_payout_batch`, `get_payout_item`, `verify_webhook(headers, body)`.
- Errors map to a `PayPalError(code, debug_id, http_status)` that is surfaced in the UI with its debug ID.

### 7.3 Endpoints (`backend/app/modules/money/`; ownership checked explicitly as in M3)
- `POST /deals/{id}/bonus-terms/preview {text}` → `{terms, examples[], max_bonus_per_video_cents, funding_total_cents}`. Brand only, and only before funding.
- `PUT /deals/{id}/bonus-terms {source_text, terms}`. Brand only, and only before funding.
- `PUT /me/brand/auto-approve-limit {cents}`.
- `POST /deals/{id}/funding/order` → `{order_id}`.
- `POST /deals/{id}/funding/capture {order_id}`. Verifies the status, the amount and `custom_id == deal.id`, then in one transaction marks the funding captured, the deal and milestones funded, writes a `money_events` row and an outbox notification.
- `POST /milestones/{id}/submissions` (multipart) → `{submission_id}`, and starts the settlement run.
- `POST /submissions/{id}/retry`.
- `GET /deals/{id}/money` → `{funding, bonus_terms, milestones[{status, owed, paid, submissions[], payouts[]}], ledger[], available_cents, can_close}`.
- `POST /payouts/{id}/approve` and `POST /payouts/{id}/reject {reason}`. Brand only.
- `POST /deals/{id}/close` → refund. Brand only.
- `GET /money/dashboard` → flat tables for AG Studio: deals, milestones, payouts, money_events, creators. Brand only.
- `POST /webhooks/paypal`. Signature-verified via `PAYPAL_WEBHOOK_ID`. Handles `PAYMENT.PAYOUTS-ITEM.*` and `PAYMENT.CAPTURE.REFUNDED`. Idempotent.
- `POST /internal/nightly` (shared secret). Polls non-terminal payouts, re-settles stale submissions, and keeps Supabase active.
- `POST /demo/reset`. Hackathon mode only.
- **Payout status**: updated from the webhook when it is available, plus a polling worker every 30 s for `sent` payouts. Webhooks cannot reach localhost during development.

### 7.4 Frontend (Next.js 16; read `node_modules/next/dist/docs` before writing code, per AGENTS.md)
- New `components/money/`:
  - `MoneyPanel`
  - `BonusTermsEditor`: text, preview, editable fields, worked examples
  - `FundWithPayPal`: JS SDK v6, with the redirect fallback
  - `SubmitProofDialog`
  - `VerdictCard`: with "Why this amount?"
  - `PayoutStatus`
  - `ApprovalCard`
  - `Ledger`
  - `CloseDealDialog`
- Supabase realtime on the money tables drives live updates. M3 uses a unique channel per subscription; follow that.
- `/brand/money`: AG Studio (`AG_STUDIO` license key) over `GET /money/dashboard`.
  - The **Claude adapter** is a `directLlmRunner` adapter in the browser. It posts to the Next.js route `/api/ai/claude`, which adds `ANTHROPIC_API_KEY` server-side, pins the model to `claude-sonnet-5-5`, caps output tokens, enforces `usage_counters` through the backend, and streams Anthropic events translated into AG-UI events (`TEXT_MESSAGE_CONTENT`, `TOOL_CALL_*`).
  - Reference: `paypaldev/hackathon-paypal-ag-grid-boilerplate` `app/dashboard/studio/openai-adapter.ts` and the AG Studio Direct LLM Runner docs.
  - **Cut line**: if the adapter is not working after 2 hours of build time, ship the dashboard with AG Studio's built-in features and a `clientToolRunner` backed by our Claude proxy.
- **Copy and trademarks**: no social-platform names or logos. Use "post", "short video" and "analytics screenshot".

---

## 8. Deployment (Render)

`render.yaml` blueprint:
- **`collabio-api`** (Python web service, Starter): `uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT`. Workers stay in the app lifespan as today (`WORKERS_ENABLED=1`).
- **`collabio-web`** (Node web service, Starter): `npm run build && npm run start`.
- **`collabio-settlement`** (Render Workflows, Python SDK): tasks `settle_submission(submission_id)` and `nightly_settlement()`, which call the same service code as the API via a shared package path.
  - The API triggers `settle_submission` through the Render SDK when `RENDER_WORKFLOWS_ENABLED=1`; otherwise it runs the task in-process.
  - **Cut line**: if the workflow service is not deployed by Nov 12, 16:00 IST, keep in-process and say so honestly in the README.
- **`collabio-nightly`** (cron, daily): `curl -X POST $API/api/v1/internal/nightly -H "X-Internal-Secret: …"`.
- **Supabase** stays hosted (the existing project). Add the `proofs` storage bucket in the migration or setup script.
- **Environment**: the existing backend and frontend variables, plus:
  - `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_ENV=sandbox`
  - `ANTHROPIC_API_KEY`
  - `HACKATHON_MODE`, `NEXT_PUBLIC_HACKATHON_MODE`
  - `AG_STUDIO`
  - `INTERNAL_SECRET`
  - `RENDER_WORKFLOWS_ENABLED`, `RENDER_API_KEY`
  - `NEXT_PUBLIC_PAYPAL_CLIENT_ID`
  - `FRONTEND_ORIGIN` set to the Render web URL.
- The repo is private until submission, so the user connects GitHub to Render once.
- **Cost**: about $14/month plus Workflows usage, paid from the $50 Render hackathon credits. Free tiers are avoided because they spin down.

---

## 9. Demo data (`backend/scripts/seed_money.py`, also used by `/demo/reset`)

- All names and content are fictional. Brand **Lumen Audio**; creator **Priya Raman** (`payout_email` = sandbox receiver); a second creator is used for dashboard variety.
- Seeded deals:
  1. **"Lumen Pods launch"**: booked, unfunded, 2 milestones of $400. This is the live demo path: the judge funds it, submits, and gets paid.
  2. **"Studio Monitors"**: funded, with one milestone already paid and one awaiting approval. This shows the approval card instantly.
  3. **"Desk Speaker"**: completed, with a refund. This fills the dashboard and the ledger.
- Historic money rows for deals 2 and 3 are seeded rows clearly labeled as seed data. Only deal 1 is guaranteed to move live sandbox money in the demo.
- **Analytics screenshots**: 3–4 PNGs generated with a fictional "Analytics" UI at different view counts (e.g. 312,000 / 812,400 / 1,240,000), committed under `frontend/public/demo/` and offered as "Use sample screenshot" in the dialog.

---

## 10. Testing

- **Pure core, test-first**:
  - `settlement.py` (§5, table-driven);
  - the BonusTerms validation;
  - the `pay_creator` decision function (limit, confidence, checks) as a pure function.
- **Adapter**: `respx` fakes for the token cache and refresh-on-401, idempotency headers, error mapping, and webhook verification.
- **API**:
  - ownership: another brand → 404, the wrong role → 403;
  - bonus terms only before funding;
  - capture verifies the amount and `custom_id`, and a double capture is idempotent;
  - approve/reject state rules;
  - close computes the refund and blocks later payouts;
  - the demo caps return 429.
- **Agent**: a fake Anthropic client with scripted tool calls. Proves that no tool path moves money beyond the engine or the limit, that a low-confidence result goes to approval, and that a model error leaves the submission retryable.
- **Live sandbox (opt-in, `-m live`)**: buyer approval cannot run headless, so the live test (1) creates an order and asserts PAYER_ACTION_REQUIRED, then (2) runs payout → status poll → refund against `PAYPAL_TEST_CAPTURE_ID`, a capture approved once by hand and stored in `.env`.
- **E2E (Playwright)**: one money-flow spec on the hosted URL. The checkout approval step is done manually, and the spec covers everything after capture.
- **Manual checklist before the video**: the full judge path on the hosted URL, in an incognito window.

---

## 11. Build order and cut lines (times in IST)

| # | Slice | Done when | Target |
|---|---|---|---|
| 1 | Hackathon mode (landing, personas, sign-up and calls off, caps) | A judge enters in one click | Nov 12, 02:00 |
| 2 | Migration, PayPal adapter, payout engine (TDD) | Unit tests green | 04:00 |
| 3 | Funding flow (bonus terms, fund, capture) end to end locally | Real sandbox capture from the UI | 06:30 |
| 4 | Submission, Claude settlement agent, payout, approval, close and refund | The full money loop works locally | 10:00 |
| 5 | Deploy to Render (API, web, cron) and seed | Hosted URL passes the judge path | 13:00 |
| 6 | AG Studio dashboard with the Claude adapter | The agent builds a widget | 16:00 |
| 7 | Render Workflows for settlement | Runs visible in the Render dashboard | 17:00 (cut line) |
| 8 | README, LICENSE (MIT), architecture diagram, judge guide, `.env.example` | Repo ready to go public | 18:00 |
| 9 | Video (AI voiceover, under 3:00), Devpost text | Public on YouTube by 20:00, submitted by 22:00 | 22:00 |

If time runs short:
- Slice 7 drops first, then the "Ask Collabio" agent (keeping the AG Studio dashboard), then the Playwright spec.
- Slices 1–5 and 8–9 are never cut.

---

## 12. Submission deliverables (from Devpost rules)

- The repo is public at submission, with an MIT `LICENSE` at the root so it shows in the About sidebar. No secrets in history; a scan on Nov 11 found only placeholders.
- The README covers:
  - what it is, who it is for, and the problem;
  - where PayPal is used (Orders, Payouts, Refunds, Webhooks) and where AI is used (Claude settlement and terms parsing, the Claude AG Studio agent, the existing Gemini and ElevenLabs features);
  - an architecture diagram;
  - the hosted URL;
  - the **judge guide**: persona buttons, and the PayPal sandbox buyer email and password;
  - local run steps;
  - sponsor tools used: AG Grid (AG Studio plus the Studio Agent Framework), Render (plus Workflows), and APIMatic (the PayPal Context Plugin, used while building).
- A Devpost description, Tools section, "Built With", and the sponsor tools selected on the form.
- A YouTube video under 3:00, AI voiceover, no copyrighted music, no third-party trademarks.
- After the deadline: no commits, and everything stays live until Dec 21.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| Next.js 16 API differences | Read the bundled docs before writing frontend code (AGENTS.md). |
| PayPal JS SDK v6 is unfamiliar | Fall back to a redirect approval via the `payer-action` link. |
| AG Studio adapter contract | Use the boilerplate adapter as a template. Cut line in §7.4. |
| Render Workflows SDK maturity | In-process fallback behind a flag. Cut line in §8. |
| Shared demo accounts mutated by many judges | Reset demo, plus the seeded deal set. Every judge path starts from "Lumen Pods launch", which the reset restores. |
| Vision misreads the views | `view_confidence` gates auto-pay. Low confidence, or a read more than 5% away from `claimed_views`, goes to brand approval. |
| Supabase free project pauses | Nightly cron ping. Mention it in the README. |
| Overnight build without the user | Every slice ends with green tests and a commit on the branch. Problems are logged in `docs/superpowers/notes/overnight-log.md` for the morning. |

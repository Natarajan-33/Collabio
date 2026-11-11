# Collabio M4: PayPal money and the Claude settlement agent (implementation plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brands fund awarded Collabio deals with PayPal Checkout. A Claude agent verifies each creator deliverable and pays it with PayPal Payouts (brand approval above a limit). The unspent budget is refunded. Brands see it all in an AG Studio dashboard. The whole app runs in a judge-safe hackathon mode on Render.

**Architecture:**
- **Backend:** new pure core modules (`settlement`, `payout_policy`), new adapters (`paypal`, `claude`, `storage`), a `money` module with a router, two agents (terms parser, settlement), and one Supabase migration.
- **Frontend (Next.js 16):** adds `components/money/*` to the existing deal pages, a hackathon landing with persona login, and `/brand/money` (AG Studio plus a Claude adapter proxied through a Next route).
- **Deployment:** Render blueprint (API, web, cron), plus a Render Workflows service as a cut-line extra.

**Tech stack:**
- Backend: FastAPI, asyncpg, Supabase (Postgres, Auth, Storage, Realtime), httpx, tenacity, `anthropic` Python SDK, pytest with respx.
- Frontend: Next.js 16.3.6, React 19, AG Studio, PayPal JS SDK v6.
- Hosting: Render.

**Spec:** `docs/superpowers/specs/2026-11-11-collabio-m4-paypal-money-design.md`. Read it with this plan; § references point there.

## Global constraints
- Work only on branch `hackathon/paypal-money`. Commit at the end of every task, with a message ending in the repo's Co-Authored-By line.
- Money is integer cents, USD only. Rounding is floor. `funding_total ≤ 1_000_000` cents (error `funding_too_large`).
- The model never supplies a money amount. Amounts come only from `app/core/settlement.py`. Auto-pay is decided only by `app/core/payout_policy.decide`.
- Defaults:
  - `brands.auto_approve_limit_cents` default **30000**, valid range 0..1000000.
  - Claimed vs. read views tolerance: **5%**.
  - Proof screenshots: PNG/JPG **≤ 5 MB**.
- Daily per-user caps (429 `demo_cap`): settlement runs 30, dashboard agent messages 40, bonus previews 30, voice sessions 15. Demo reset is limited to 1 per minute.
- Models: `claude-sonnet-5-5` (settlement, vision, dashboard agent) and `claude-haiku-5-5` (bonus-term parsing).
- PayPal sandbox only (`https://api-m.sandbox.paypal.com`):
  - PayPal wallet checkout only; never `payment_source.card`.
  - Never use the hosted PayPal MCP server.
  - Use the token from the client ID and secret, never a pasted token.
- Hackathon mode is **flags, not deletions** (`HACKATHON_MODE`, `NEXT_PUBLIC_HACKATHON_MODE`).
- No social-platform names or logos anywhere (UI, seed, screenshots, copy). Use "post", "short video" and "analytics screenshot".
- Secrets live only in env (`backend/.env`, `frontend/.env.local`, Render env). Never commit them. Update both `.env.example` files whenever you add a variable.
- **Frontend:** read the relevant guide in `frontend/node_modules/next/dist/docs/` before writing Next.js code (AGENTS.md: "This is NOT the Next.js you know"). After any backend schema change, run `npm run api:gen`.
- **Backend tests** hit the hosted Supabase and are slow. Run only the task's test files, never the whole suite, and use `-p no:cacheprovider -q`.
- PayPal credentials for local development are in `D:\Github\All-Hackathons\Paypal-oct2026\.env`. Copy the PayPal, Anthropic and AG Studio values into `backend/.env` and `frontend/.env.local`, and never print them.
- Collabio's backend runs on **port 8001** locally, because 8000 is the user's founder-intel server. Start the frontend with `NEXT_PUBLIC_API_URL=http://localhost:8001`.

## Review focus
1. **Double-clicked or retried "Fund"/capture:** exactly one `deal_funding` capture and one `funded` money event. A second capture returns the existing result. Test in Task 8.
2. **Two settlement runs racing on the same milestone** (two judges, retry plus a new submission): never two payouts for the same delta. The milestone row is locked during quote and pay, and `sender_batch_id` is unique. Test in Task 10.
3. **PayPal errors after a payout row exists** (422/5xx on create): the row becomes `failed`, `available` is restored, and the UI shows the PayPal `debug_id`. No silent loss. Test in Task 11.
4. **A bad proof upload** (not an image, over 5 MB, or an image with no readable views): 422 for the file, or the agent sets `needs_changes` or `approval`. Never auto-pay. Test in Task 10.
5. **Closing a deal while a payout is `sent`/`awaiting_approval`:** the refund excludes committed amounts, and payout attempts after close are rejected with 409 `deal_closed`. Test in Task 11.

---

## File map

**Backend (`backend/`)**

| File | Responsibility |
|---|---|
| `supabase/migrations/20261111120000_m4_money.sql` | §7.1 schema, RLS, the `proofs` bucket, the money_events append-only trigger |
| `app/config.py` (modify) | New settings fields |
| `app/core/settlement.py` | Pure payout engine (§5) |
| `app/core/payout_policy.py` | Pure auto-pay vs. approval decision |
| `app/core/caps.py` | Cap limits table and `cap_for(kind)` |
| `app/adapters/paypal.py` | PayPal REST client (§7.2) |
| `app/adapters/claude.py` | Thin Anthropic wrapper with a port for fakes |
| `app/adapters/storage.py` | Supabase Storage upload and signed URLs |
| `app/agents/terms_parser.py` | Haiku bonus-terms parser |
| `app/agents/settlement_agent.py` | Sonnet tool-use loop (§6) |
| `app/modules/money/repo.py`, `service.py`, `runner.py`, `usage.py`, `demo.py` | Data access, orchestration, settlement dispatch, caps, demo reset |
| `app/schemas/money.py` | Pydantic request and response models |
| `app/api/routers/money.py`, `internal.py`, `demo.py` | HTTP endpoints (§7.3) |
| `app/api/deps.py` (modify) | `get_paypal`, `get_claude`, `get_storage`, `require_internal_secret` |
| `app/workers/payouts.py` | Polls `sent` payouts every 30 s |
| `scripts/seed_money.py` | §9 demo data, shared by `/demo/reset` |
| `tests/fakes.py` (modify) | `FakePayPal`, `FakeClaude`, `FakeStorage` |
| `workflows/settlement.py` | Render Workflows tasks (cut-line Task 16) |

**Frontend (`frontend/`)**

| File | Responsibility |
|---|---|
| `lib/hackathon.ts` | `isHackathon` flag and persona constants |
| `app/page.tsx` (modify) | Hackathon landing (§3) |
| `app/api/demo-login/route.ts` | Server-side persona sign-in |
| `app/(auth)/layout.tsx` (modify) | Redirect to `/` in hackathon mode |
| `components/shell/PersonaSwitcher.tsx` | Switch persona, plus Reset demo |
| `components/money/*.tsx` | MoneyPanel, BonusTermsEditor, FundWithPayPal, SubmitProofDialog, VerdictCard, PayoutStatus, ApprovalCard, Ledger, CloseDealDialog |
| `lib/money/api.ts` | Typed calls for the money endpoints |
| `app/brand/deals/[id]/page.tsx`, `app/creator/deals/[id]/page.tsx` (modify) | Mount the money components |
| `app/brand/money/page.tsx`, `app/brand/money/studio/*` | AG Studio dashboard |
| `lib/ai/claude-adapter.ts`, `app/api/ai/claude/route.ts` | AG Studio ↔ Claude bridge |
| `public/demo/analytics-*.png` | Generated fictional screenshots |

**Root:** `render.yaml`, `LICENSE`, `README.md` (rewritten top section), `docs/architecture.md`.

---

## Slice 1: Hackathon mode and foundations

### Task 1: M4 migration
**Files:** Create `backend/supabase/migrations/20261111120000_m4_money.sql`. Test `backend/tests/db/test_m4_money_schema.py`.

**Interfaces.** Produces these tables and columns, exactly as spec §7.1:
- `deal_bonus_terms`, `deal_funding`, `milestone_submissions` (including `claimed_views int not null`), `settlement_runs`, `payouts`, `money_events`, `usage_counters`;
- `brands.auto_approve_limit_cents`, `creators.payout_email`;
- the extended status checks on `deals` (`booked|funded|completed`) and `deal_milestones` (`pending|funded|submitted|needs_changes|verified|paid`);
- a private storage bucket `proofs` (`insert into storage.buckets (id, name, public) values ('proofs','proofs',false) on conflict do nothing`);
- the trigger `money_events_append_only`, which raises on UPDATE/DELETE unless `current_setting('collabio.demo_reset', true) = 'on'`.

RLS on every new table:
- select policy: the deal's brand owner or creator owner, mirroring the `deals` policies in `20261014120000_m3_deal_loop.sql`;
- `usage_counters`: no policies.

Steps:
- [ ] Write tests:
  - `test_new_tables_exist`
  - `test_money_events_rejects_update` (expect an `asyncpg.RaiseError`)
  - `test_payout_sender_batch_id_unique`
  - `test_deal_status_accepts_funded_completed`
  - `test_brand_cannot_read_other_brands_payouts` (RLS through a `set local role authenticated` plus a JWT-claims pattern, as in the M3 db tests)
- [ ] Run `uv run pytest tests/db/test_m4_money_schema.py -p no:cacheprovider -q`. Expect FAIL.
- [ ] Write the migration, then apply it: `uv run python -m scripts.apply_migration supabase/migrations/20261111120000_m4_money.sql`.
- [ ] Re-run the tests. Expect PASS.
- [ ] Commit `feat(db): m4 money schema`.

### Task 2: Settings, hackathon guards, usage caps
**Files:**
- Modify `app/config.py`, `app/api/deps.py`, `app/api/routers/voice.py` (try-call), and the outreach launch code that reads `ChannelPlan` (`app/modules/outreach/service.py`, around the `channels` mapping in `app/schemas/briefs.py:116`).
- Create `app/core/caps.py` and `app/modules/money/usage.py`.
- Tests: `tests/core/test_caps.py`, `tests/api/test_hackathon_mode.py`.

**Interfaces. Produces:**
- `Settings` fields:
  - `hackathon_mode: bool = False`
  - `paypal_client_id`, `paypal_client_secret` (repr=False), `paypal_webhook_id`, `paypal_base_url = "https://api-m.sandbox.paypal.com"`, `paypal_test_capture_id = ""`
  - `anthropic_api_key` (repr=False), `claude_settlement_model = "claude-sonnet-5-5"`, `claude_parser_model = "claude-haiku-5-5"`
  - `internal_secret` (repr=False)
  - `render_workflows_enabled: bool = False`, `render_api_key` (repr=False), `render_workflow_slug = "collabio-settlement"`
- `caps.LIMITS = {"settlement": 30, "agent_message": 40, "bonus_preview": 30, "voice_session": 15}`, `cap_for(kind: str) -> int`.
- `usage.consume(db, user_id: UUID, kind: str) -> None`: does an upsert-increment on `(user_id, current_date, kind)` and raises `HTTPException(429, "demo_cap")` when the count after the increment exceeds the cap. It is a no-op unless `hackathon_mode`.
- `deps.require_internal_secret`: a header dependency on `X-Internal-Secret`.

Steps:
- [ ] Write tests:
  - `test_cap_for_known_kinds`
  - `test_try_call_forbidden_in_hackathon_mode`: POST `/api/v1/try-call` returns 403 with detail `disabled_in_demo`.
  - `test_launch_coerces_call_plans_to_email`: in hackathon mode a brief launched with `call`/`email_then_call` stores the plan `email`.
  - `test_consume_raises_429_after_cap`: settlement, 31st call.
- [ ] Run them and confirm they fail.
- [ ] Implement.
- [ ] Re-run and confirm they pass.
- [ ] Wire voice-session start to `usage.consume(..., "voice_session")`. The voice token endpoint is in `routers/voice.py`.
- [ ] Add the new variables to `backend/.env.example`.
- [ ] Commit `feat(hackathon): settings, call guards and usage caps`.

### Task 3: Frontend hackathon landing and personas
**Files:**
- Create `lib/hackathon.ts`, `app/api/demo-login/route.ts`, `components/shell/PersonaSwitcher.tsx`.
- Modify `app/page.tsx`, `app/(auth)/layout.tsx`, the brand and creator shell headers (in `components/shell/`), and the call buttons and call channel options in `components/board/*` and `components/brief/*` (find them with `rg -n "call" components/board components/brief`).

**Interfaces. Produces:**
- `isHackathon = process.env.NEXT_PUBLIC_HACKATHON_MODE === "1"`.
- `GET /api/demo-login?as=brand|creator`:
  - signs in server-side using `@supabase/ssr` with `DEMO_BRAND_EMAIL`/`DEMO_HELPER_EMAIL` and `DEMO_PASSWORD` (server-only env);
  - redirects to `/brand` or `/creator`;
  - returns 404 when not in hackathon mode.

**Copy, fixed by spec §3:**
- Landing buttons: "Enter as Lumen Audio (brand)" and "Enter as Priya (creator)".
- Call button tooltip: "Calls are off in the public demo."
- The Judge guide drawer shows the sandbox buyer email and password from `NEXT_PUBLIC_JUDGE_BUYER_EMAIL` and `NEXT_PUBLIC_JUDGE_BUYER_PASSWORD`. These are sandbox-only and intentionally public.

Steps:
- [ ] Read `node_modules/next/dist/docs` on route handlers and cookies.
- [ ] Write a Vitest test `lib/hackathon.test.ts`: `personaPath("brand") === "/brand"` and `personaPath("creator") === "/creator"`.
- [ ] Implement the route, the landing, the switcher (Brand, Creator, Reset demo; Reset calls `POST /api/v1/demo/reset`, which Task 13 adds), the `(auth)` redirect, and the hidden or disabled call UI.
- [ ] Run `npm run typecheck && npm run lint && npm test` and confirm they pass.
- [ ] **Manual check:** `/` shows the two buttons, each lands signed in, and `/sign-up` redirects to `/`.
- [ ] Add the variables to `frontend/.env.example`.
- [ ] Commit `feat(hackathon): persona landing and switcher`.

## Slice 2: Pure core and the PayPal adapter

### Task 4: Payout engine
**Files:** Create `app/core/settlement.py`. Test `tests/core/test_settlement.py`.

**Interfaces. Produces** (frozen dataclasses):
- `Cpm(rate_cents_per_1k: int, starts_after_views: int, cap_cents: int)`
- `Tier(views: int, bonus_cents: int)`
- `BonusTerms(cpm: Cpm | None, tiers: tuple[Tier, ...])`
- `MilestoneState(amount_cents: int, verified: bool, best_verified_views: int, committed_cents: int)`

**Functions:**
- `validate_terms(t) -> list[str]` returns codes from `{"tiers_unsorted", "tiers_duplicate", "too_many_tiers", "non_positive"}`.
- `bonus_for(views: int, t: BonusTerms | None) -> int`
- `max_bonus_per_video(t) -> int`
- `funding_total(amounts: list[int], videos: int, t) -> int` raises `ValueError("funding_too_large")` above 1_000_000.
- `owed(m, t) -> int`
- `delta(m, t) -> int`
- `available(captured: int, committed_all: int, refunded: int) -> int`
- `payable(m, t, available_cents: int) -> int`
- `refund_due(captured, committed_all, refunded) -> int`
- `breakdown(m, t) -> dict` with keys `base, cpm, tiers, already_committed, delta`.
- `terms_to_json(t) -> dict` and `terms_from_json(d) -> BonusTerms`.

The formulas are exactly spec §5.

Steps:
- [ ] Write table-driven tests with these exact cases. `T = BonusTerms(Cpm(200, 200_000, 50_000), (Tier(1_000_000, 30_000),))`:

| Call | Expected |
|---|---|
| `bonus_for(150_000, T)` | `0` |
| `bonus_for(200_000, T)` | `0` |
| `bonus_for(812_400, T)` | `min(50_000, 612_400*200//1000) = 50_000` |
| `bonus_for(400_000, T)` | `40_000` |
| `bonus_for(1_000_000, T)` | `80_000` |
| `max_bonus_per_video(T)` | `80_000` |
| `funding_total([40_000, 40_000], 2, T)` | `240_000` |
| `delta(MilestoneState(40_000, True, 400_000, 40_000), T)` | `40_000` |
| A resubmission with lower views (`best_verified_views` unchanged) | `0` |
| `payable(..., available_cents=10_000)` | `10_000` (clamped) |
| `refund_due(240_000, 120_000, 0)` | `120_000` |
| `validate_terms` on unsorted tiers | includes `"tiers_unsorted"` |
| `funding_total` over the limit | raises |
| `None` terms | bonus `0` |

- [ ] Run `uv run pytest tests/core/test_settlement.py -q` and confirm it fails.
- [ ] Implement.
- [ ] Re-run and confirm it passes.
- [ ] Commit `feat(core): deterministic payout engine`.

### Task 5: Payout policy
**Files:** Create `app/core/payout_policy.py`. Test `tests/core/test_payout_policy.py`.

**Interfaces. Produces** `decide(payable: int, limit: int, view_confidence: Literal["high","medium","low"], views_read: int, claimed_views: int, brief_ok: bool, disclosure_ok: bool) -> Literal["none","auto","approval"]`:
1. `"none"` if `payable == 0`.
2. `"auto"` only if `payable ≤ limit` and the confidence is not low and `abs(views_read − claimed_views) ≤ 0.05 × max(claimed_views, 1)` and `brief_ok` and `disclosure_ok`.
3. Otherwise `"approval"`.

Steps:
- [ ] Write tests:
  - `test_zero_is_none`
  - `test_under_limit_all_ok_is_auto`
  - `test_over_limit_is_approval` (limit 30000, payable 30001)
  - `test_low_confidence_is_approval`
  - `test_claimed_mismatch_over_5pct_is_approval` (read 812_400, claimed 700_000)
  - `test_exactly_5pct_is_auto`
  - `test_disclosure_missing_is_approval`
- [ ] Confirm they fail.
- [ ] Implement.
- [ ] Confirm they pass.
- [ ] Commit `feat(core): payout policy`.

### Task 6: PayPal adapter
**Files:** Create `app/adapters/paypal.py`. Modify `app/api/deps.py` (`get_paypal`) and `tests/fakes.py` (`FakePayPal`). Test `tests/core/test_paypal_client.py`.

**Interfaces. Produces:**
- `PayPalError(Exception)` with `code: str`, `debug_id: str | None`, `http_status: int`, `message: str`.
- `class PayPalClient(client_id, client_secret, base_url, http: httpx.AsyncClient | None = None)` with async methods:
  - `create_order(amount_cents, custom_id, invoice_id, description, return_url, cancel_url) -> dict` (id, status, approve_url)
  - `get_order(order_id) -> dict`
  - `capture_order(order_id) -> dict` (status, capture_id, amount_cents, custom_id)
  - `refund_capture(capture_id, amount_cents, note) -> dict` (id, status)
  - `create_payout(sender_batch_id, receiver_email, amount_cents, note) -> dict` (batch_id, item_id | None, batch_status)
  - `get_payout_batch(batch_id) -> dict` (batch_status, item_id, item_status, errors)
  - `verify_webhook(headers: Mapping[str, str], body: bytes, webhook_id: str) -> bool`
- Amounts convert between cents and PayPal decimal strings (`"12.34"`).
- The order body uses `payment_source.paypal.experience_context` with `user_action: "PAY_NOW"` and `shipping_preference: "NO_SHIPPING"`. This is the shape proven by the Nov 11 smoke test (spec §2).
- `FakePayPal` implements the same methods in memory and records calls.

Steps:
- [ ] Write respx tests:
  - `test_token_cached_until_5min_before_expiry`
  - `test_refreshes_token_once_on_401`
  - `test_every_post_sends_unique_paypal_request_id`
  - `test_error_maps_to_paypalerror_with_debug_id` (422 body with `details[0].issue = "PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING"` → `code` equals that issue)
  - `test_cents_to_decimal_string` (12_345 → "123.45")
  - `test_capture_parses_capture_id_and_custom_id`
- [ ] Confirm they fail.
- [ ] Implement (tenacity retry on 429/5xx, 3 attempts).
- [ ] Confirm they pass.
- [ ] Commit `feat(paypal): sandbox REST adapter`.

## Slice 3: Funding

### Task 7: Claude adapter, bonus-terms parser, bonus and limit endpoints
**Files:**
- Create `app/adapters/claude.py`, `app/agents/terms_parser.py`, `app/schemas/money.py`, `app/modules/money/repo.py`, `app/modules/money/service.py`, `app/api/routers/money.py`.
- Modify `app/main.py` (include the router), `app/api/deps.py` (`get_claude`), `tests/fakes.py` (`FakeClaude`), and `pyproject.toml` (add `anthropic` via `uv add anthropic`).
- Tests: `tests/core/test_terms_parser.py`, `tests/api/test_money_bonus.py`.

**Interfaces. Produces:**
- `ClaudePort` protocol: `async def create(*, model: str, system: str, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 1024) -> dict`. It returns the Anthropic message as a dict: `content` blocks and `stop_reason`.
- `ClaudeClient(api_key)` implements it with `anthropic.AsyncAnthropic`.
- `FakeClaude(script: list[dict])` returns the scripted messages in order and records requests.
- `parse_bonus_terms(claude, model, text) -> BonusTerms | str`. It uses a single forced tool `set_bonus_terms` whose JSON schema mirrors `BonusTerms` in dollars and view counts, then converts to cents. It returns a question string when the model calls `ask_question(question)`, or when `validate_terms` fails.
- Endpoints:
  - `POST /deals/{id}/bonus-terms/preview` returns `BonusPreview {terms, examples: [{views, bonus_cents}] for 100_000/500_000/1_000_000, max_bonus_per_video_cents, funding_total_cents}`, or 422 `{detail: "terms_question", question}`.
  - `PUT /deals/{id}/bonus-terms {source_text, terms}`.
  - `PUT /me/brand/auto-approve-limit {cents}`.
- All endpoints are brand-owner only (other brand → 404, creator → 403). Bonus endpoints return 409 `already_funded` after funding. Preview consumes `bonus_preview`.
- `MoneyService(db, paypal, claude, settings, storage=None)` is the class later tasks extend. Task 10 passes `storage`.

Steps:
- [ ] Write tests:
  - `test_parser_converts_dollars_to_cents` (FakeClaude returns `set_bonus_terms` with `cpm: {rate_per_1k: 2, starts_after_views: 200000, cap: 500}`, `tiers: [{views: 1000000, bonus: 300}]` → `Cpm(200, 200000, 50000)`, `(Tier(1000000, 30000),)`)
  - `test_parser_returns_question_on_invalid_terms`
  - `test_preview_examples_and_funding_total` (seeded 2×$400 deal → `funding_total_cents == 240000`)
  - `test_put_bonus_terms_409_after_funding`
  - `test_other_brand_gets_404`
  - `test_limit_out_of_range_422`
- [ ] Confirm they fail.
- [ ] Implement.
- [ ] Confirm they pass.
- [ ] Commit `feat(money): bonus terms with the Claude parser`.

### Task 8: Funding order, capture, money view
**Files:** Modify `app/modules/money/{repo,service}.py`, `app/api/routers/money.py`, `app/schemas/money.py`. Test `tests/api/test_money_funding.py`.

**Interfaces. Produces:**
- `POST /deals/{id}/funding/order` returns `{order_id, approve_url}`:
  - `custom_id = str(deal_id)`, `invoice_id = f"collabio-{deal_id}-{n}"`;
  - `return_url = f"{public_frontend_url}/brand/deals/{id}?funding=return"`;
  - upserts `deal_funding(status='created')`.
- `POST /deals/{id}/funding/capture {order_id}`, in one transaction with `select … for update` on `deal_funding`:
  - if it is already `captured`, return the existing view;
  - otherwise capture, then assert `custom_id == deal_id` and `amount == funding_total` (else 409 `funding_mismatch`);
  - set the deal to `funded`, the milestones to `funded`, insert a `money_events` row (`funded`), and add a `creator_funded` outbox email plus a realtime notify, following M3's outbox pattern.
- `GET /deals/{id}/money` returns `MoneyView`: `funding, bonus_terms, auto_approve_limit_cents, milestones[{id, seq, title, amount_cents, status, owed_cents, committed_cents, submissions[], payouts[]}], ledger[], available_cents, can_close`. The brand owner or creator owner can read it. Creators never see `auto_approve_limit_cents` (it is null for them).

Steps:
- [ ] Write tests (FakePayPal):
  - `test_order_then_capture_marks_funded_and_ledger`
  - `test_double_capture_is_idempotent` (**review focus 1**: two concurrent `capture` calls via `asyncio.gather` produce exactly one `funded` event)
  - `test_capture_amount_mismatch_409`
  - `test_creator_money_view_hides_limit`
- [ ] Confirm they fail.
- [ ] Implement.
- [ ] Confirm they pass.
- [ ] Commit `feat(money): fund deals with PayPal checkout`.

### Task 9: Frontend money panel (fund flow)
**Files:**
- Create `lib/money/api.ts`, `components/money/MoneyPanel.tsx`, `BonusTermsEditor.tsx`, `FundWithPayPal.tsx`, `Ledger.tsx`.
- Modify `app/brand/deals/[id]/page.tsx`.
- Regenerate `lib/api/schema.d.ts` with `npm run api:gen`.

**Interfaces.**
- Consumes the Task 7 and Task 8 endpoints.
- `FundWithPayPal` loads PayPal JS SDK v6 with `NEXT_PUBLIC_PAYPAL_CLIENT_ID` and creates the order through the backend. On approval it calls capture.
- **Fallback, decided now:** if v6 is not working within 45 minutes, render a "Pay with PayPal" button that sends the browser to `approve_url`. The deal page handles `?funding=return&token=<order_id>` by calling capture once.
- `MoneyPanel` states: Not funded (BonusTermsEditor, limit field, Fund), Funded (amounts, milestones, Ledger), Completed.
- Money formatting reuses `lib/money.ts`.

Steps:
- [ ] Read the Next 16 docs for client components and search params.
- [ ] Write a Vitest test `components/money/format.test.ts` for `formatExamples([{views: 1_000_000, bonus_cents: 80000}]) → "1M views → +$800"`.
- [ ] Implement.
- [ ] Run `npm run typecheck && npm run lint && npm test`.
- [ ] **Manual check** (backend on 8001): preview the bonus, fund through the sandbox buyer, and see the deal show Funded with a ledger row.
- [ ] Commit `feat(web): fund deals with PayPal`.

## Slice 4: Settlement

### Task 10: Proof submission, storage, settlement agent, in-process runner
**Files:**
- Create `app/adapters/storage.py`, `app/agents/settlement_agent.py`, `app/modules/money/runner.py`.
- Modify `app/modules/money/{repo,service}.py`, `app/api/routers/money.py`, `tests/fakes.py` (`FakeStorage`).
- Tests: `tests/core/test_settlement_agent.py`, `tests/api/test_money_settlement.py`.

**Interfaces. Produces:**
- `Storage(supabase_url, secret_key)`:
  - `upload(path, data: bytes, content_type) -> None` via `POST {url}/storage/v1/object/proofs/{path}`;
  - `signed_url(path, ttl_s=3600) -> str`.
- `POST /milestones/{id}/submissions` (multipart: `post_url`, `caption`, `claimed_views`, `screenshot`), creator owner only:
  - the milestone must be `funded`, `needs_changes` or `paid` (else 409 `not_submittable`);
  - the screenshot must have a PNG/JPG magic number and be ≤ 5 MB (else 422 `bad_screenshot`);
  - consumes `settlement`;
  - inserts the submission, sets the milestone to `submitted`, calls `runner.start(submission_id)`, and returns `{submission_id}`.
- `POST /submissions/{id}/retry`.
- `runner.start(submission_id)`: when `render_workflows_enabled`, Task 16 replaces this; otherwise it does `asyncio.create_task(service.settle(submission_id))`, keeping a reference set.
- `MoneyService.settle(submission_id)` creates `settlement_runs` (unique; if it already exists and is `done`, return) and calls `run_settlement`.
- `run_settlement(deps: SettlementDeps, submission_id) -> RunResult(status, decision, payout_id | None)` is a Sonnet loop of at most 8 steps:
  - The first user message includes the screenshot as an image block (base64 from storage) plus the context text.
  - Tools exactly as spec §6: `get_deal_context`, `record_verification`, `quote_payout`, `pay_creator`, `request_changes`.
- `pay_creator`, in one transaction:
  1. `select … for update` the milestone row, then re-quote with `settlement.payable`;
  2. call `payout_policy.decide`;
  3. `auto` inserts a `payouts` row with status `approved`, `sender_batch_id = f"collabio-{payout_id}"`, then calls `paypal.create_payout` after commit, sets the row to `sent`, and adds money events `payout_queued` and `payout_sent`;
  4. `approval` inserts a row with status `awaiting_approval` and the event `payout_queued`;
  5. on a verified milestone, set the milestone to `verified` (it becomes `paid` in Task 11 once its payout succeeds).
- The transcript is saved to `settlement_runs.transcript`.
- A model error or more than 8 steps sets the run to `error`, the submission stays `submitted`, and retry is allowed.

Steps:
- [ ] Write tests (FakeClaude scripts and FakePayPal):
  - `test_happy_path_auto_pays_under_limit` (brand limit 100_000; T from Task 4; milestone base 40_000; views read 400_000 and claimed 400_000; brief and disclosure OK; confidence high → payable 80_000 → `auto`) → one payout with status `sent` and `FakePayPal.create_payout` called once with `receiver_email == creator.payout_email`. Also `test_same_case_with_limit_30000_goes_to_approval`.
  - `test_model_amount_is_ignored` (the script passes `amount` in `pay_creator` args, and the payout still equals the engine's value)
  - `test_low_confidence_goes_to_approval`
  - `test_request_changes_sets_needs_changes_no_money`
  - `test_concurrent_settles_same_milestone_single_payout` (**review focus 2**: two submissions settled via `asyncio.gather` give total committed == owed)
  - `test_bad_screenshot_422` (**review focus 4**: a text file named `.png`; a 6 MB PNG)
  - `test_model_error_leaves_retryable`
- [ ] Confirm they fail.
- [ ] Implement.
- [ ] Confirm they pass.
- [ ] Commit `feat(money): Claude settlement agent pays via PayPal Payouts`.

### Task 11: Approvals, close and refund, payout status, webhook, nightly
**Files:**
- Modify `app/modules/money/{repo,service}.py`, `app/api/routers/money.py`.
- Create `app/workers/payouts.py`, `app/api/routers/internal.py`.
- Modify `app/main.py` (lifespan starts the payouts worker when `workers_enabled`; include the routers) and `app/api/routers/webhooks.py` (add `/webhooks/paypal`).
- Test `tests/api/test_money_payouts.py`.

**Interfaces. Produces:**
- `POST /payouts/{id}/approve`: brand only; status must be `awaiting_approval`; re-checks `available`; sends via PayPal, sets the row to `sent`, and adds the event `payout_sent`.
- `POST /payouts/{id}/reject {reason}`: sets the row to `rejected`, the event to `payout_rejected`, the submission to `needs_changes`, and stores the reason as `agent_summary`.
- `POST /deals/{id}/close`: brand only; requires `can_close` (all milestones `paid`, or today > `go_live_by` + 7 days). It refunds `settlement.refund_due` with `paypal.refund_capture` if the amount is greater than 0, adds to `refunded_cents`, writes the event `refunded`, and sets the deal to `completed`.
- Any payout attempt or approval on a completed deal returns 409 `deal_closed`.
- `MoneyService.sync_payout(payout_id)`: maps PayPal item status `SUCCESS` to `success` (the milestone becomes `paid` and the event `payout_succeeded`), and `FAILED|RETURNED|BLOCKED|DENIED` to `failed` (event `payout_failed`). `PENDING`/`UNCLAIMED` leave it unchanged.
- The worker calls `sync_payout` for `sent` rows every 30 s.
- `POST /webhooks/paypal` verifies the signature with `paypal_webhook_id` (when it is empty, ignore and return 202), then calls `sync_payout` by `sender_batch_id`/`payout_item_id`. It is idempotent.
- `POST /internal/nightly` (requires the internal secret) syncs every `sent` payout, retries runs stuck in `error` older than 10 minutes, and returns counts.

Steps:
- [ ] Write tests:
  - `test_approve_sends_and_marks_sent`
  - `test_reject_sets_needs_changes`
  - `test_paypal_error_on_send_marks_failed_and_restores_available` (**review focus 3**: FakePayPal raises `PayPalError(code="INSUFFICIENT_FUNDS", debug_id="abc")` → row `failed`, event `payout_failed` with `debug_id` in the payload, `available_cents` unchanged from before)
  - `test_close_refunds_unspent_excluding_committed` (**review focus 5**: one payout `sent` for 40_000 of a 240_000 capture → refund 200_000)
  - `test_payout_after_close_409`
  - `test_sync_success_marks_milestone_paid`
  - `test_nightly_requires_secret`
- [ ] Confirm they fail.
- [ ] Implement.
- [ ] Confirm they pass.
- [ ] Commit `feat(money): approvals, refunds and payout status`.

### Task 12: Frontend settlement UI
**Files:**
- Create `components/money/SubmitProofDialog.tsx`, `VerdictCard.tsx`, `PayoutStatus.tsx`, `ApprovalCard.tsx`, `CloseDealDialog.tsx`.
- Modify `app/creator/deals/[id]/page.tsx`, `app/brand/deals/[id]/page.tsx`, `components/money/MoneyPanel.tsx`.
- Add `hooks/use-money-realtime.ts`.

**Interfaces.**
- Consumes the Task 8, 10 and 11 endpoints.
- Realtime: subscribe to `payouts`, `milestone_submissions` and `money_events` filtered by the deal's milestones, on a unique channel name per subscription (M3 rule, see commit d0ed4dd), and refetch `GET /deals/{id}/money` on any event.
- SubmitProofDialog has a "Use sample screenshot" picker over `/demo/analytics-*.png` (from Task 13). It fetches the PNG as a blob and submits it as the file.
- VerdictCard shows the checks, the views read vs. claimed, the breakdown (base / CPM / tiers / already paid), and the "Why this amount?" disclosure of the run summary.
- PayoutStatus shows Pending → Paid with the PayPal IDs.
- ApprovalCard has Approve and Reject (reason required).
- CloseDealDialog shows the refund amount before confirming.
- Errors with a `debug_id` are shown as "PayPal said: <code> (debug <id>)".

Steps:
- [ ] Write a Vitest test for `breakdownLines()` (a pure formatter).
- [ ] Implement.
- [ ] Run typecheck, lint and test.
- [ ] **Manual check** of the full loop locally: fund → submit sample → verdict → payout Pending → Paid (within about 60 s through the worker) → close → refund in the ledger.
- [ ] Commit `feat(web): proof, verdict, approvals and close`.

### Task 13: Demo seed, reset, sample screenshots, live sandbox test
**Files:**
- Create `scripts/seed_money.py`, `app/modules/money/demo.py`, `app/api/routers/demo.py`, `frontend/public/demo/analytics-312k.png`, `analytics-812k.png`, `analytics-1240k.png`, and `tests/live/test_paypal_sandbox.py`.

**Interfaces. Produces:**
- `seed_money(conn) -> dict[str, UUID]`, idempotent, implementing spec §9:
  - deal titles "Lumen Pods launch", "Studio Monitors", "Desk Speaker";
  - Priya's `payout_email` set from `PAYPAL_RECEIVER_EMAIL`.
  - It creates the deals directly (thread, deal and milestones inserts reusing `modules/deals/repo.insert_deal`/`insert_milestones`), on top of the existing seed's brand and creators.
- `POST /api/v1/demo/reset`: hackathon mode only, 1 per minute (in-memory timestamp). It runs `set local collabio.demo_reset = 'on'`, deletes the money rows for the three demo deals, and calls `seed_money`.
- **Screenshots:** generated by a small Playwright script (`frontend/scripts/make-demo-shots.ts`) that renders a fictional "Analytics" card (title "Post analytics", big view number, likes and shares, no logos) to PNG, then commits the PNGs.
- **Live test** (`-m live`, skipped without `PAYPAL_CLIENT_ID`):
  - `test_create_order_requires_payer_action`;
  - `test_payout_and_refund_on_test_capture` (uses `PAYPAL_TEST_CAPTURE_ID`, refunds $1, pays $1 to `PAYPAL_RECEIVER_EMAIL`, polls to SUCCESS within 90 s).

Steps:
- [ ] Write `test_seed_money_idempotent` in `tests/db` (two runs, same deal IDs and row counts) and `test_reset_requires_hackathon_mode`.
- [ ] Confirm they fail.
- [ ] Implement and generate the PNGs.
- [ ] Confirm they pass.
- [ ] Run the live test once: `uv run pytest tests/live/test_paypal_sandbox.py -m live -q`.
- [ ] Commit `feat(demo): money seed, reset and sample screenshots`.

## Slice 5: Deploy

### Task 14: Render deployment
**Files:** Create `render.yaml` and `docs/deploy.md`.

**Interfaces. Produces the services named in spec §8:**
- `collabio-api`: Python, Starter, `rootDir: backend`, build `pip install uv && uv sync --frozen`, start `uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT`, health check `/api/v1/health`.
- `collabio-web`: Node, Starter, `rootDir: frontend`, build `npm ci && npm run build`, start `npm run start`.
- `collabio-nightly`: cron `0 3 * * *`, `curl -fsS -X POST $API_URL/api/v1/internal/nightly -H "X-Internal-Secret: $INTERNAL_SECRET"`.
- The env var list goes in `docs/deploy.md`, with values set in the Render dashboard (`sync: false` in the blueprint for secrets).

Steps:
- [ ] Write `render.yaml`.
- [ ] Run `npm run build` locally for the frontend, then confirm the backend starts with `HACKATHON_MODE=1`.
- [ ] Ask the user to connect GitHub to Render and create the Blueprint from the private repo. **This needs the user.** Until then, continue with Task 15 locally and log it in `docs/superpowers/notes/overnight-log.md`.
- [ ] After deploy:
  - set `FRONTEND_ORIGIN`, `PUBLIC_FRONTEND_URL` and `PUBLIC_BACKEND_URL` to the Render URLs;
  - register the PayPal webhook for `PAYMENT.PAYOUTS-ITEM.*` and `PAYMENT.CAPTURE.REFUNDED` to `https://<api>/api/v1/webhooks/paypal` through the REST API (`POST /v1/notifications/webhooks`), and store `PAYPAL_WEBHOOK_ID`;
  - run seed and reset.
- [ ] **Verify:** an incognito judge path on the hosted URL passes, from fund to refund. The Playwright money spec from spec §10 is cut (§11 allows it), and this manual path replaces it.
- [ ] Commit `chore(deploy): render blueprint`.

## Slice 6: AG Studio dashboard

### Task 15: `/brand/money` with the Claude agent
**Files:**
- Create `app/brand/money/page.tsx`, `app/brand/money/studio/{config.ts,data.ts}`, `lib/ai/claude-adapter.ts`, `lib/ai/claude-adapter.test.ts`, `app/api/ai/claude/route.ts`.
- Modify the brand nav (`components/shell/*`), backend `app/api/routers/money.py` (`GET /money/dashboard`), and `app/api/routers/internal.py` (`POST /internal/usage/agent_message`, which the Next route calls with the internal secret plus the user id to consume the cap).

**Interfaces.**
- `GET /money/dashboard` (brand) returns `{deals[], milestones[], payouts[], money_events[], creators[]}` as flat rows with cents and ISO dates.
- `claude-adapter.ts` exports `createClaudeAdapter(endpoint = "/api/ai/claude")`, which implements AG Studio's `directLlmRunner` adapter contract.
  - **Before coding**, read `paypaldev/hackathon-paypal-ag-grid-boilerplate/app/dashboard/studio/openai-adapter.ts` (fetch it with `gh api`) and the AG Studio "Direct LLM Runner" docs (Context7, or ag-grid.com/studio/react/ai-agents/).
  - Mirror the OpenAI adapter's shape, swapping in the request mapping to the Anthropic Messages API and translating the streamed Anthropic events to AG-UI events.
- `route.ts` streams `POST https://api.anthropic.com/v1/messages` with `ANTHROPIC_API_KEY` (server env). The model is pinned to `claude-sonnet-5-5` and `max_tokens ≤ 2048`. It consumes the `agent_message` cap through the backend first.
- **Cut line (spec §7.4):** if the adapter isn't streaming correctly by 2 hours into this task, use a `clientToolRunner` whose `run` calls the route non-streaming. Log the decision.
- The dashboard has KPI tiles (funded, paid, pending approval, refunded), spend vs. budget per deal, cost per 1K views per creator, payouts over time, and bonus vs. base. The theme matches the app (dark).

Steps:
- [ ] Write a Vitest test `claude-adapter.test.ts`: translating a recorded Anthropic SSE fixture (`message_start`, `content_block_delta` text, `tool_use` start, `message_stop`) produces `RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START` … in order.
- [ ] Confirm it fails.
- [ ] Implement.
- [ ] Confirm it passes.
- [ ] **Manual check:** ask "show cost per 1K views by creator" and see a widget appear.
- [ ] Commit `feat(web): AG Studio money dashboard with a Claude agent`.

## Slice 7: Render Workflows (cut line: Nov 12, 16:00 IST)

### Task 16: Settlement on Render Workflows
**Files:** Create `backend/workflows/settlement.py`. Modify `app/modules/money/runner.py` and `render.yaml`.

**Interfaces.**
- Before coding, read https://render.com/docs/workflows-sdk-python and `render-examples` (fetch with `gh`/WebFetch).
- Define the tasks `settle_submission(submission_id: str)` and `nightly_settlement()`. Both build a `MoneyService` from env and call `settle`/`nightly`.
- `runner.start` triggers `settle_submission` through the Render SDK or REST API when `render_workflows_enabled`, and falls back to in-process on any error. Log a warning.
- The nightly cron calls the workflow instead of the endpoint when it is enabled.

Steps:
- [ ] Write `test_runner_falls_back_in_process_on_trigger_error` (monkeypatch the trigger to raise; the settle task still runs).
- [ ] Confirm it fails.
- [ ] Implement.
- [ ] Confirm it passes.
- [ ] Deploy the workflow service and confirm a run appears in the Render dashboard for a real submission.
- [ ] Commit `feat(render): settlement on Render Workflows`.

## Slice 8: Submission readiness

### Task 17: README, LICENSE, architecture, env examples
**Files:** Create `LICENSE` (MIT, `Copyright (c) 2026 Natarajan Mohankumar`) and `docs/architecture.md` (a Mermaid diagram of browser → Next → FastAPI → PayPal / Claude / Supabase / Render Workflows). Modify `README.md`, `backend/.env.example`, `frontend/.env.example`.

**The README top section contains these, in order** (spec §12):
1. The one-line pitch.
2. The problem and the audience.
3. The hosted URL and the **Judge guide**: the persona buttons, plus the sandbox buyer email and password.
4. A "How money moves" diagram.
5. Where PayPal is used: Orders v2 checkout and capture, Payouts, Refunds, Webhooks.
6. Where AI is used:
   - Claude settlement agent with vision;
   - Claude terms parser;
   - Claude AG Studio agent;
   - the existing Gemini search and ElevenLabs voice.
7. Sponsor tools: AG Grid (AG Studio plus the Studio Agent Framework), Render (plus Workflows), APIMatic (PayPal Context Plugin used while building).
8. Local run steps.
9. Hackathon-mode notes: calls are off, plus the caps.
10. License.

Steps:
- [ ] Write the files.
- [ ] Run `rg -n "sk-ant|sb_secret|EKOj|client_secret=" -g '!*.lock'` across the repo and confirm there are no hits outside `.env*`, which is git-ignored.
- [ ] Confirm `git check-ignore backend/.env frontend/.env.local` lists both.
- [ ] Commit `docs: README, license and architecture for submission`.

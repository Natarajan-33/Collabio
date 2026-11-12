# Overnight log: Nov 12, 2026 (03:20 → morning IST)

Branch `hackathon/paypal-money`, pushed to the private `origin`. The ledger has every decision:
`.superpowers/sdd/2026-11-11-collabio-m4-paypal-money/progress.md` (lines with `Ruling:` / `Final:`).

## Morning: what needs you (in order, about 20 minutes)

1. **Render: add a payment card** (Render requires one before it creates paid Starter services,
   even with the $50 credit). Dashboard → Billing → add card. I stopped at that screen and
   entered nothing.
2. **Create the Blueprint**: Dashboard → New → Blueprint → repo `Collabio`, branch
   `hackathon/paypal-money`, name `collabio-paypal-hackathon`. When it asks for the secret
   values you can leave them empty, because step 4 fills them. Click **Apply**.
3. **Create a Render API key**: Account settings → API Keys → Create. Add it to
   `D:\Github\Collabio\backend\.env` as `RENDER_API_KEY=...` (the file is git-ignored). Then tell me "key added".
4. From then on I can do everything myself:
   - `render_env push --deploy`, which sets every env var from the local `.env` files and prints names only;
   - PayPal webhook registration;
   - the `collabio-settlement` workflow (Dashboard → New → Workflow; see `docs/deploy.md`). This one may
     need you to click "Create" if the API cannot do it;
   - an incognito check of the judge path on the hosted URL.
5. **The one PayPal sandbox checkout for the video.** Logging in to PayPal (even sandbox) is a
   password on a third-party site, so I don't type it. I'll open a recording browser, and you log in
   with the sandbox buyer account and click **Pay** once. About 1 minute.
6. **Supabase setting to check**: Authentication → Providers → Email → make sure **sign-ups are
   disabled** (the public demo should only use the two personas). The reviewer flagged that open
   sign-up multiplies the AI caps.
7. **YouTube**: upload the video I produce to @NattyNeuron as **Public** (I'll give you the file,
   title and description). Then make the repo public, and the Devpost form (I'll draft every field).

## Done tonight

| Task | Commit | Notes |
|---|---|---|
| 15: AG Studio money dashboard + Claude agent | `bd262fd` | Deals-grid fan-out fixed; Edit-mode crash fixed (layout colours from CSS tokens); per-creator cost per 1K views; agent cap counts turns; seed sets brief asking price (the brand Offers page 500'd in the demo); live check: the agent builds "cost per 1K views by creator" |
| 14: Render blueprint (code) | `fb1a755` | `render.yaml` (Singapore, next to Supabase ap-south-1), `docs/deploy.md`, `scripts/render_env.py`, `scripts/register_paypal_webhook.py`. **Blocked on the card** (step 1) |
| 17: README, LICENSE, architecture | `88955c4` | Judge guide with the sandbox buyer; APIMatic plugin installed and used (its Python SDK skills reviewed our retry/idempotency design); hosted URL to be confirmed after deploy |
| 16: Render Workflows (code) | `a97c8f2` | `backend/workflows/settlement.py` (`settle_submission`, `nightly_settlement`); API triggers it when `RENDER_WORKFLOWS_ENABLED=1`, else in-process; deploy pending |
| Stale tests | `393a3b7`, `69b127c` | cap pin, lifespan fake, shell/deal-page tests for the Money item and money panel |
| Final whole-branch review + fix pass | `ec2e427`, `524352f` | 0 Critical, 6 Important (all fixed test-first, RED verified against the old code), 7 Minor deferred |

### What the final review fixed
1. A payout could be marked `failed` while PayPal actually paid it (overlapping resend, or a
   duplicate-request 4xx after a timeout). The send now claims the row, and a 4xx after an unknown outcome stays
   `approved` and is flagged.
2. A capture that succeeded at PayPal but failed for us could be orphaned by clicking Fund again. Fund
   now completes the earlier approved or captured order.
3. A low-confidence earlier read could drive an auto-pay. Auto-pay now needs the submission behind the
   best view count to pass too.
4. A zero-views read could auto-pay the base. It now goes to approval.
5. `/api/ai/claude` was an open Sonnet proxy. The body is now sanitised and size-limited, there is a daily token
   ceiling, and `max_tokens` is 4096.
6. One visitor could exhaust the shared demo caps. Caps are now charged after validation, there are per-IP
   sub-caps, and the persona caps are raised.

### Afternoon (Nov 12): deployed and demo polished
- **Live:** https://collabio-web.onrender.com (API https://collabio-api.onrender.com). Every env var was set by
  `scripts/render_env.py`. PayPal webhook `5F132631K8389983T` is registered. The persona redirect bug
  (redirects pointed at `localhost:10000`) is fixed. The hosted judge path passes 7/7 in a fresh browser.
- **Demo data:** test leftovers removed with `scripts/clean_demo.py` (63 briefs, 59 batches, 67 threads,
  and a stray "Lumen Pods" deal). There are now four demo deals: Priya has Lumen Pods (the live path) and Studio Monitors;
  the second creator **Arjun Mehta** has Desk Speaker (refunded) and Soundbar review (1.5M views), so the
  dashboard compares two creators. I kept 2 offers to Priya and Arjun from the brand "Fusion 3d" (a gmail account, probably
  yours); `clean_demo.py --apply --include-other-brands` removes them if you want.
- **Two deferred minors fixed:** the dashboard bonus/base split ("Bonus paid" now counts each payout's own
  share, successful payouts only), and the capture-failure toast (it now names the bonus-changed case and shows PayPal's debug id).

### Deferred minors (not fixed; your call)
- A PENDING capture is marked failed with no refund, and a true mismatch leaves captured money unrefunded.
- A payout 429 that survives retries is marked failed (safe; the creator resubmits).
- The `PAYMENT.CAPTURE.REFUNDED` webhook is ignored (refunds are synchronous anyway).
- A run killed mid-flight shows "checking" until the 5-minute reclaim.
- There's no approval badge in the nav, and the Playwright money spec was cut (spec §11).

## Tests run tonight

All green at the end of the night (HEAD `6c55d07`):

| Suite | Result |
|---|---|
| Backend, full (in chunks: core, db, workers, api ×3) | **≈1,350 passed, 0 failing** (core 732, db 94, workers 64, api 162 + 118 + 180) |
| Frontend: typecheck, lint, all Vitest | **936 passed**, 0 errors (1 old lint warning in an e2e spec) |
| Production build (`npm run build`) | passed |
| Live PayPal sandbox (`tests/live/test_paypal_sandbox.py -m live`) | **2 passed** (real order, $1 refund, $1 payout) |
| Real Claude settlement, API level | worked: read 312K views (high confidence), then **refused to pay** because the caption was about the wrong product (needs changes with a note to the creator); no money moved |
| Dashboard agent in the browser (Playwright) | "Add a chart of effective cost per 1,000 views by creator" → the chart appears |

How the sweep went, and what it caught:
- The Supabase connection dropped several times overnight (`WinError 121` / closed connections).
  The test harness fails every later DB test once one connect fails, so I reran in chunks and retried
  the chunks that hit it. None of these were code failures.
- It caught one real bug that I introduced: adding the Render SDK pulled in `aiohttp`, which silently switched Gemini's
  client off httpx (retries and test mocks bypassed). Fixed in `524352f`.
- Stale tests updated: the cap pins, the lifespan fake, the Money rail item, the deal page's money panel,
  and the offers tests (the shared demo creator also holds the money demo's deals).

The demo was reseeded and the usage counters cleared after the last test run.

## Video (prepared, waiting for your two choices)
- Script draft (three hooks): `D:\Github\All-Hackathons\Paypal-oct2026\submissionideo-script.md`, and
  as the animate-video skill's demo script: `D:\Github\Collabio.animate\demo-paypal-money_script.json`
  (validated). Devpost text draft: `...\submission\devpost.md`.
- Pipeline: the `animate-video` skill's demo mode (Playwright capture of the real app, local Kokoro
  voiceover, HyperFrames motion graphics, critic panel). It needs from you: (1) pick the hook and approve
  the script, (2) pick the design, (3) a yes to clicking Fund, Submit and Approve on camera (the skill
  bans clicking pay/submit by default; ours are sandbox), and (4) a yes to the small Claude spend of
  the recorded runs.

## Things I noticed
- `backend/.env`: `ELEVENLABS_WEBHOOK_SECRET` holds what looks like the webhook *path* from the
  README, not a secret. Voice calls are off in hackathon mode, so it is harmless for the demo.
- Tests and the live demo share one Supabase project and the same demo brand. Some tests reset
  the brand's auto-approve limit to $300. **Rerun `uv run python -m scripts.seed_money`** after
  any test run (I do this at the end of the night), and clear `usage_counters`.
- The local backend workers must be off (`WORKERS_ENABLED=0`) once Render is live, and while tests run.
- The project started on Oct 9, inside the submission period, so the "existed before Oct 1" Devpost question
  doesn't apply.

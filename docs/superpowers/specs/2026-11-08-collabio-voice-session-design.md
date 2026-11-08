# Collabio — The Voice Session (Design Spec)

| | |
|---|---|
| **Date** | 2026-11-08 |
| **Status** | Approved in brainstorming (§1–§5); awaiting written-spec review |
| **Builds on** | `docs/superpowers/specs/2026-10-14-collabio-m3-deal-loop-design.md` (M3, done) |
| **Reference** | The scripted sample on tenvexalabs.in: `D:\Github\tenvexalabs\components\sections\voice-demo-stage.tsx`, script in `lib/site.ts` (`howItWorks.demo`) |
| **Branch** | `feat/voice-session`, cut from `release/next` at `faddb35`. `release/next` stays the fallback. |
| **Path** | Architectural: this spec, then one implementation plan |

---

## 1. Intent

### 1.1 Why
The Tenvexa Labs site shows a Collabio request as one fluent loop: **Speak → See → Refine → Confirm**. A brand says one sentence, three creators appear, one is swapped by voice, and one sheet approves the send. The product today needs four screens (Discover → Review → Brief → Launch) and two voice systems for the same job, and it cannot refine without starting over.

The product's complexity (packages, briefs, private limits, negotiation by email and phone) stays. The voice session hides it behind the sample's interaction. A complex product that feels this simple is the selling point.

### 1.2 Sub-projects (agreed order)
| # | Sub-project | Contents |
|---|---|---|
| **1** | **Voice session** (this spec) | One-screen session on Discover: refine without reset, swap/remove/add, summary line, compound commands, brief fields by voice, confirm sheet |
| 2 | US + India markets | USD/INR per brand and creator, ₹/lakh/"40k" in speech, city-level location and search, formatting. The website sample (₹, Bengaluru) works literally after this. |
| 3 | M4 Money | As in the M3 spec's roadmap, now designed for both currencies |

### 1.3 Decisions made in brainstorming
1. **Discover becomes the session.** The confirm moment happens on the same screen as search and refine. Review and the brief page remain, reached through *Compare packages* and *Edit*.
2. **Nothing is guessed.** Collabio never fills a brief value the brand did not say, type or click. Values come from the brand's words, from the brand's profile (brand, product, summary, contact email, as today), or from an explicit click. Missing values are asked for on the sheet.
   - *"Keep each under $2k"* is said by the brand, so it is recorded as the budget cap (and used as the search's price filter).
   - *"For our March launch"* names the campaign and leaves a hint. It does **not** fill the go-live date.
   - *"Find three creators"* fills the shortlist. It does **not** set how many to hire.
3. **One voice system.** Push-to-talk (the existing dock) for the whole session. The sheet shows what is still needed as short questions. Collabio does not talk back, matching the sample and keeping voice cost down. The talking ElevenLabs brief agent stays on the full brief page.
4. **The session is a draft brief.** The first pick creates a draft brief on the server; every change after that saves to it. Approve calls the existing launch. *Edit* opens the same brief. The draft id is in the URL.
5. **Voice never approves.** Approve & send is a click, as everywhere else.

### 1.4 Success criteria
1. Typed or spoken, *"Find three fitness creators for our March launch. Keep each under two thousand dollars."* produces, in one command: a fitness search under $2,000, a shortlist of the top 3, campaign name "March launch", budget cap $2,000, and a sheet that asks for the go-live date with the hint "you said March".
2. *"Swap Meera for someone who does home workouts"* replaces Meera **in her row** with the best home-workout match under the current filters, marked *Updated*. If there is none, Meera stays and the summary line says why.
3. Refinements keep every filter not mentioned (*"make it under 1,500"* keeps the niche; *"drop the price limit"* removes only the price).
4. Approve & send is enabled only when nothing required is missing, no rule is broken, and the server's draft has the shortlist on screen. It launches and opens the board.
5. Every value on the sheet can be traced to the brand's words, a click, or the brand profile.
6. The M1–M3 suites keep passing; Review, the brief page and the board behave as before.

### 1.5 Out of scope
INR, cities and other currencies (sub-project 2); spoken replies (TTS); cleaning up abandoned drafts; any creator-side change; choosing a package per creator on the sheet (still done on Review).

---

## 2. The session screen (`/brand/discover`)

Top to bottom:

1. **Header and summary line.** The heading stays. Below it, one line describing what the last command did, built from the actual results by a deterministic function (§5.2), never written by the model. Examples: *"✦ Found 3 matches under $2,000, sorted by engagement"*, *"✦ Swapped Meera for Ishaan · still under your cap"*, *"✦ Couldn't use 1 Jan: it's in the past"*.
2. **Shortlist** (once anyone is picked). One row per creator: initials, name, handle, niche, followers · engagement, and the price of their compared package. A creator swapped or added by the last command is outlined and marked **Updated** until the next command. On Discover this replaces the floating selection tray.
3. **More matches.** The existing card grid, still clickable to add or remove, with the existing Flip animations.
4. **Confirm sheet** (sticky at the bottom while the shortlist is non-empty):
   - **Title:** `Start {reachable} negotiations · listed total {sum} · Brief: {campaign_name ?? product_name}`. When some creators cannot be contacted: `· {n} can't be contacted`.
   - **Most you'd spend:** `budget_ceiling × hires_target`, once both are known. Shown to the brand only.
   - **Checklist**, in this order. Answered fields show their value and a small "from what you said" marker when voice filled them; clicking one opens the existing inline field editor. Unanswered fields show as questions:

     | Field | Question when missing |
     |---|---|
     | `campaign_name` (optional) | Name this campaign? (optional) |
     | `hires_target` | How many of these {n} do you want to hire? |
     | `deliverables_count` + `deliverables_format` | How many videos each, in what format? |
     | `go_live_by` | Go-live date? (+ hint, e.g. "you said March") |
     | `budget_ceiling_cents` | Most you'll pay per creator? (private) |
     | `ask_price_cents` | Opening offer per creator? |
     | `negotiation_ask` | What should we negotiate for? |
     | `flexibility` | Where are you flexible? |

   - **From your profile** (collapsed line): brand, product, contact email. Changed through *Edit*.
   - **Contact plan:** each creator's default channel from the preview, and follow-up policy `suggest`. Shown as one line ("Email first · change in Edit"). These are operational defaults the product already uses, not brief terms.
   - **Buttons:** *Edit* (full brief page, same brief), *Compare packages* (Review), **Approve & send** (locked with the reasons on hover or focus, like today's Launch bar).
5. **URL:** `/brand/discover?brief=<id>` once a draft exists, so a reload or another device resumes the session.

---

## 3. The voice router

### 3.1 The `session` command
On the `discover` screen the allowed kinds become `session`, `clear_selection`, `open_review`, `navigate` (and `unclear`). `search` and `select` remain on `review`. The other screens do not change.

The model returns `RoutedSession`. The page applies its parts in this fixed order:

1. **`brief`:** brief fields that were said: `campaign_name`, `hires_target`, `deliverables_count`, `deliverables_format`, `go_live_by`, `budget_ceiling_cents`, `ask_price_cents`, `negotiation_ask`, `flexibility`. Plus `go_live_hint` (free text such as "March") when a period was named without a date.
2. **`search`:** `mode` is `refine` (default) or `new` (the brand clearly changed topic: "show me beauty creators instead"). `query`, `filters` (only what was said), `clear` (dimensions to remove: `query`, `niches`, `content_types`, `max_price`, `min_followers`, `region`), `sort`.
3. **`remove_names`, `add_names`, `swap`:** names as said; `swap` = `{ out_name, replacement: { query, filters } }`.
4. **`top_n` + `top_n_mode`:** `replace` (default: "find three") or `add` ("three more", "also add the top two").

Prompt rules added to `ROUTER_SYSTEM`:
- "Under/below/max $X each" also sets `brief.budget_ceiling_cents` to X when it describes what the brand will pay a creator.
- Dates are ISO dates from explicit days only. A month, season or event ("March", "Diwali", "our launch") goes in `go_live_hint`, never in `go_live_by`.
- How many to hire is set only from explicit wording ("hire all three", "we'll take two").
- The existing money and vocabulary rules apply unchanged.

### 3.2 Context sent with each command
`VoiceContext` gains:
- `current_search`: the session's `SearchRequest` (query, filters, sort).
- `shortlist`: `CreatorRef[]` in shortlist order.
- `brief_status`: `{ filled: string[], missing: string[], campaign_name: string | null }`. Field names only; no money values.

`router_prompt` prints these next to the existing visible creators.

### 3.3 What the service does (`modules/voice/service.py`)
`_to_intent` turns `RoutedSession` into `VoiceIntent.session` (`SessionCommand`):
- Names resolved to ids with `resolve_creator_refs` against shortlist + visible creators. A swap whose `out_name` matches no one on the shortlist is dropped; the outcome lists it in `skipped` so the summary line can say so.
- Each brief field is checked with `brief_rules.field_error(name, value, today)`. Failures are dropped and returned in `rejected: [{ field, message }]`. Cross-field rules (ask above cap, more hires than creators) are not checked here; the draft brief reports them as violations.
- A session with no usable part becomes `unclear` with suggestions, as today.

### 3.4 How the page applies a command (`lib/session/`)
- **Refine merge:** for each search dimension, a said value replaces the current one; dimensions in `clear` are emptied; everything else is kept. `mode: new` starts from empty filters.
- **Swap:** search with `merge(current, replacement)`; take the first result not already on the shortlist; put it at the `out` creator's index; mark it *Updated*. No result: keep the creator and report it.
- **Pick:** `top_n` from the (new) results; `replace` sets the shortlist, `add` appends without duplicates. The cap of 10 holds (existing message).
- **Brief fields:** PATCH the draft. If no draft exists yet, hold them in session state and send them in the first PATCH right after the draft is created.

---

## 4. Backend

### 4.1 Search sort
- `SearchRequest.sort: Literal["relevance", "followers", "engagement", "price"] | None`. `None` keeps today's behaviour (relevance with a query, followers without).
- One migration replaces `public.match_creators` with an extra `sort_by text default null` parameter. The filters are unchanged. Order by:
  - `relevance`: distance nulls last, followers desc, id
  - `followers`: followers desc, distance nulls last, id
  - `engagement`: engagement_rate desc nulls last, distance nulls last, id
  - `price`: the creator's cheapest package that passes the price and content-type filters, ascending, then distance nulls last, id
- The return type is unchanged. Execution stays revoked from `public`, `anon` and `authenticated`.

### 4.2 Briefs
- **`creator_ids` on `BriefPatch`:** 1–10 ids, duplicates dropped, order kept, each a listed creator (the same check as create; `UnknownCreators` → 422). A launched brief returns 409 as today. The preview follows the new list.
- **`campaign_name`:** new nullable column on `deal_briefs` (`text`, 1–80 characters after trimming). It is in `BriefFields`, the PATCH and the board's batch header. It is **not** a required field. It is brand-only: never in outreach emails, call variables or the brief agent's creator-facing text.
- **`hires_target` becomes required:**
  - `deal_briefs.hires_target` becomes nullable with no default. Existing rows keep their values. `batches.hires_target` stays `not null`, and launch copies the value as today.
  - `hires_target` is added to `REQUIRED_BRIEF_FIELDS` (after `flexibility`). A PATCH with `null` clears it (today it resets to 1).
  - New cross-field rule: `hires_target` greater than the brief's creator count is a violation ("You picked fewer creators than you want to hire").
  - `DealBrief.hires_target: int | None`. The brief page's stepper shows "—" until it is set.
  - The ElevenLabs brief agent's `missing_fields` variable leaves `hires_target` out (the stepper handles it; the agent's tool cannot set it).
- **Listed total:** the sum of `package.base_price_cents` over the reachable creators in `GET /briefs/{id}/preview`. Computed in the frontend from the preview; no new endpoint.

### 4.3 Voice schemas (`schemas/voice.py`)
New: `SearchSort`, `SessionSearch`, `RoutedSwap`, `RoutedSession`, `SessionBrief`, `SessionSwap`, `SessionCommand`, `BriefStatus`. `IntentKind` gains `session`. `ALLOWED_INTENTS["discover"]` becomes `{"session", "clear_selection", "open_review", "navigate"}`. `DEFAULT_SUGGESTIONS["discover"]` is updated to session examples. The OpenAPI types used by the frontend are regenerated.

---

## 5. Frontend

### 5.1 Units
| Unit | Purpose |
|---|---|
| `lib/session/state.ts` | Pure: session state (brief id, search, shortlist, updated ids, pending brief fields, go-live hint) and reducers: refine merge, swap in place, pick, remove, add |
| `lib/session/summary.ts` | Pure: the summary line from a command's outcome |
| `lib/session/sheet.ts` | Pure: sheet rows (answered or question), title, totals, lock reasons |
| `hooks/use-session-brief.ts` | Creates and PATCHes the draft; tracks `synced` (server creator list equals the shortlist and no PATCH is in flight); loads `?brief=` on arrival |
| `components/session/summary-line.tsx` | The ✦ line |
| `components/session/shortlist.tsx` | Rows with the *Updated* marker |
| `components/session/confirm-sheet.tsx` | Title, totals, checklist (reuses `components/brief/field-editor.tsx`), buttons |
| `app/brand/discover/page.tsx` | Composes the above; registers the `discover` voice screen with the new context; applies `session` intents in §3.1 order |

### 5.2 Summary line rules
One sentence, at most two clauses, in this priority order: rejected fields → search outcome (count, price cap, sort) → shortlist change (picked / swapped / removed / added) → fields filled ("Noted: cap $2,000, campaign March launch") → skipped names. When a command did nothing visible, the line says what was heard instead.

### 5.3 Review and the brief page
- Review keeps working off the shared selection. When a session draft exists, its primary button reads **Back to your request** (to `discover?brief=<id>`) instead of creating a second brief. Removals there update the shared selection; the session syncs them on return.
- The brief page's back link goes to `discover?brief=<id>`. Everything else on it is unchanged, apart from the `hires_target` "—" state.

---

## 6. Errors and edge cases

| Case | Behaviour |
|---|---|
| Router unavailable or command unclear | As today: dock error or suggestions, words kept for retry, session unchanged |
| Part of a command fails | Each part is applied independently; field-rule failures are skipped and named in the summary line; cross-field conflicts are saved and shown as violations |
| PATCH fails | The shortlist stays as shown; a toast offers a retry; Approve stays locked until `synced` |
| Swap finds nobody | Creator kept; the summary line explains |
| Shortlist over 10 | Existing cap message |
| `?brief=` is not this brand's / not found | The parameter is dropped; a fresh session starts with a toast |
| `?brief=` is launched | Go straight to its board |
| Creators who opted out of contact | Marked on their row; excluded from the title count |
| Launch race (409) or stale brief (422) | Existing paths: open the board, or refresh and show what is needed |
| Reduced motion | No animation for new rows or *Updated*; the outline still shows |
| Typed commands | Same path as spoken |

Privacy: the budget cap and "most you'd spend" appear only on the brand's sheet. `campaign_name` never reaches creators. The M3 privacy sweep is extended to assert both.

---

## 7. Testing

- **Backend (pytest, fake Gemini):** sort orders, including price by cheapest matching package (`tests/api/test_discovery.py`); `creator_ids` PATCH on draft and launched briefs, plus unknown ids (`test_briefs.py`); `campaign_name` bounds; `hires_target` required, the null clear and the more-hires-than-creators rule (`tests/core/test_brief_rules.py`, `test_launch.py`); the migration (`test_apply_migration.py`); session routing: name resolution, refine vs new, rejected fields, wrong-screen kinds → `unclear`, discover no longer returning `search`/`select` (`test_voice.py`); privacy sweep for `campaign_name` and the cap (`test_m3_privacy.py`).
- **Live router evals (`tests/live/test_intent_live.py`, real Gemini):** the success-criteria sentence (no `go_live_by`, hint "March"); the swap; "make it under 1,500"; "drop the price limit"; several brief fields in one sentence; "three more" → `add`; "hire all three".
- **Frontend (vitest):** `lib/session/*` reducers, summary and sheet; `use-session-brief` sync and `?brief=` loading; the Discover page wired to fake intents; Review's "Back to your request"; the brief page's "—" stepper.
- **E2E (Playwright, `tests/e2e/session.spec.ts`):** the sample run typed into the dock: request → 3 rows → swap → answer the questions → Approve → board.
- **Regression:** `m1`, `m2`, `m3` E2E specs and all existing unit suites pass.

---

## 8. Branch and rollout
- All work lands on `feat/voice-session`, cut from `release/next`. `release/next` and `main` are not touched.
- The branch is pushed only when the user asks (a pushed branch may create a Vercel preview, which is not production).
- When the user approves the result, `feat/voice-session` merges into `release/next`. If it is not good enough, the branch is dropped and `release/next` remains as it is.
- The migration is additive except for `deal_briefs.hires_target` losing its `not null` and default. Existing rows keep their values, but drafts saved by the new code may hold `null`, which the old code cannot read. The branch therefore ships a reverse script (`backend/supabase/rollback/…_voice_session_down.sql`) that sets `null` targets to 1, restores `not null default 1`, and drops `campaign_name` and the `sort_by` overload. Run it on any database the migration reached before falling back to `release/next`.

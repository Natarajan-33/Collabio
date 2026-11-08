# Collabio Voice Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/brand/discover` into a one-screen Speak → See → Refine → Confirm session backed by a draft brief, so a brand can request, refine, complete and launch a campaign by voice and one click.

**Architecture:** The backend gains a search sort, editable creators on a draft brief, `campaign_name`, a required (confirmed) hire target, and a `session` voice command that bundles brief fields, a refining search, remove/add/swap and top-N. The frontend applies a session command with pure reducers (`lib/session/`), keeps the draft brief in sync through one hook, and shows a summary line, a shortlist and a confirm sheet on Discover.

**Tech Stack:** FastAPI + Pydantic + asyncpg on hosted Supabase Postgres (pytest, `uv run`); Next.js 16 + React 19 + openapi-fetch (vitest, Playwright); Gemini for routing.

**Spec:** `docs/superpowers/specs/2026-11-08-collabio-voice-session-design.md`

## Global Constraints

- Branch: all commits on `feat/voice-session`. Never commit to, push or merge into `release/next` or `main`. Push nothing unless the user asks.
- Shared database: tests, dev and the deployed app use one hosted Supabase project. Schema changes must be additive and keep working for the code on `main`. **Applying the migration is outward-facing: ask the user before running it** (`uv run python -m scripts.apply_migration <file>` from `backend/`).
- Run backend tests with the dev backend's workers off (`WORKERS_ENABLED=0`). Commands: `cd backend; uv run pytest -q <path>`; DB tests are marked `db`; live tests `uv run pytest -m live <path>` spend Gemini quota.
- After any change to a backend request/response model: `cd frontend; npm run api:gen`, and commit `frontend/lib/api/openapi.json` and `schema.d.ts` with that task.
- Next.js 16 differs from training data: read the relevant guide in `frontend/node_modules/next/dist/docs/` before using `useSearchParams`, `useRouter` or Suspense boundaries (AGENTS.md).
- **Nothing is guessed:** no brief value is filled unless the brand said, typed or clicked it, or it comes from the brand profile (brand, product, summary, contact email). Month/season phrases go to `go_live_hint`, never `go_live_by`. Hire count only from explicit wording.
- Voice never approves or launches. Approve & send is a click.
- Privacy: the budget cap, "most you'd spend" and `campaign_name` never reach creators (emails, call variables, offers, deals).
- Money is integer US cents; display through `formatCents` (`frontend/lib/money.ts`).
- Shortlist cap: 10 (`MAX_SELECTED`, `SELECTION_CAP_MESSAGE` in `frontend/lib/discover/state.ts`).
- Copy is fixed by the spec §2 (sheet title, questions) and §5.2 (summary line); the exact strings are in the tests below.
- Name change from the spec: the spec's `BriefStatus` context model is called `SessionBriefStatus` here, because `BriefStatus` already exists in `app/schemas/briefs.py`.

## Review Focus

1. **Two commands back to back.** The dock blocks while routing, but the page's own search and PATCH calls run after routing. A second command must be applied only after the first finished applying; otherwise the swap reads stale results. Pinned in Task 13 (`applies session commands one at a time`).
2. **Clicks while a PATCH is in flight.** A card toggled while the previous creator PATCH is pending must leave `synced` false until the server holds the latest shortlist; a late reply for an older list must not mark it synced. Pinned in Task 11 (`an older reply does not mark a newer shortlist synced`).
3. **Swap naming someone not on the shortlist** (removed earlier, or only in the grid). Nothing changes; the name is reported. Pinned in Task 7 (`swap out_name not on the shortlist is skipped`) and Task 10 (summary).
4. **"Find three" with fewer matches.** Pick what exists and say so ("Picked the top 2 of 2 matches"). Pinned in Task 9 (`pick takes what exists`) and Task 10.
5. **Fields said before any pick, then a reload.** Pending fields live in session storage and are sent right after the draft is created. Pinned in Task 11 (`pending fields survive a reload and go out after create`).

---

## File Structure

**Backend**
| File | Change |
|---|---|
| `backend/supabase/migrations/20261108120000_voice_session.sql` | Create: `campaign_name`, `hires_target_confirmed` (+ backfill), `match_creators` with `sort_by` |
| `backend/app/schemas/discovery.py` | `SearchSort`, `SearchRequest.sort` |
| `backend/app/modules/discovery/repo.py`, `service.py` | pass `sort_by` |
| `backend/app/schemas/briefs.py` | `campaign_name`, `hires_target` required, `BriefPatch.creator_ids`, `DealBrief.hires_target: int \| None` |
| `backend/app/core/brief_rules.py` | labels, `campaign_name` rule, hires-vs-creators rule |
| `backend/app/modules/briefs/service.py`, `repo.py`, `voice_session.py` | confirmed flag, creator PATCH, agent's missing list |
| `backend/app/schemas/board.py`, `modules/board/repo.py`, `service.py` | `campaign_name` on the board's brief summary |
| `backend/app/schemas/voice.py` | session models, `ALLOWED_INTENTS`, context |
| `backend/app/modules/voice/prompts.py`, `service.py` | session prompt rules, context lines, `_to_intent` session branch |

**Frontend**
| File | Change |
|---|---|
| `frontend/lib/session/state.ts` | Create: pure session state and reducers |
| `frontend/lib/session/summary.ts` | Create: summary line |
| `frontend/lib/session/sheet.ts` | Create: sheet rows, title, totals, locks |
| `frontend/hooks/use-session-brief.ts` | Create: draft brief create/PATCH/sync/launch |
| `frontend/components/session/summary-line.tsx`, `shortlist.tsx`, `confirm-sheet.tsx` | Create |
| `frontend/app/brand/discover/page.tsx` | Compose the session |
| `frontend/lib/brief/state.ts`, `components/brief/field-editor.tsx` | `campaign_name` field, `hires_target` label |
| `frontend/app/brand/discover/review/page.tsx`, `app/brand/briefs/[id]/page.tsx`, `app/brand/batches/[id]/page.tsx` | back links, "—" stepper, campaign header |
| `frontend/tests/e2e/session.spec.ts` | Create |

---

### Task 1: Migration

**Files:**
- Create: `backend/supabase/migrations/20261108120000_voice_session.sql`
- Create: `backend/tests/db/test_voice_session_schema.py`
- Modify: `backend/tests/db/test_match_creators.py`

**Interfaces:**
- Produces: `public.briefs.campaign_name text null check (campaign_name is null or char_length(btrim(campaign_name)) between 1 and 80)`; `public.briefs.hires_target_confirmed boolean not null default false` (existing rows backfilled `true`); `public.match_creators(query_embedding, max_price_cents, content_types, niches, region, min_followers, match_limit, registered_only, sort_by text default null)` with `sort_by` in `('relevance','followers','engagement','price')` or null.

- [ ] **Step 1: Write the failing schema tests** in `test_voice_session_schema.py` (pattern of `tests/db/test_m3_schema.py`):
  - `test_campaign_name_is_optional_and_bounded`: insert brief with null → ok; `"x"*81` → `asyncpg.CheckViolationError`; `"   "` → `CheckViolationError`.
  - `test_hires_target_confirmed_defaults_false`: a newly inserted brief reads `false` and `hires_target = 1`.
  - `test_launched_briefs_were_backfilled`: `select count(*) from public.briefs where status = 'launched' and not hires_target_confirmed` is 0 (every launched brief predates this code).
  - `test_old_named_call_still_resolves`: calling `match_creators` with only the eight old named arguments returns rows ordered as before (distance, followers).
- [ ] **Step 2: Write the failing sort tests** in `test_match_creators.py`, using its `match()` helper and factory region:
  - `test_sort_by_engagement`: three creators with engagement 2.0, 7.4, null → order 7.4, 2.0, null.
  - `test_sort_by_followers_ignores_distance`: with an embedding, the most-followed comes first.
  - `test_sort_by_price_uses_cheapest_matching_package`: creator A packages $500 long_video + $3,000 short_video, B $1,000 short_video; `content_types=['short_video']`, `sort_by='price'` → B, A.
  - `test_unknown_sort_is_rejected`: `sort_by='random'` raises `asyncpg.exceptions.InvalidParameterValueError`.
- [ ] **Step 3: Run to verify they fail**
  Run: `cd backend; uv run pytest -q tests/db/test_voice_session_schema.py tests/db/test_match_creators.py`
  Expected: new tests FAIL (column/parameter does not exist).
- [ ] **Step 4: Write the migration.** `alter table public.briefs add column campaign_name …, add column hires_target_confirmed boolean not null default false; update public.briefs set hires_target_confirmed = true;` then `drop function public.match_creators(extensions.vector, integer, text[], text[], text, integer, integer, boolean);` and `create function` with the M3 parameters plus `sort_by text default null`, now `language plpgsql` (so it can validate): start the body with `#variable_conflict use_column`, then `if sort_by is not null and sort_by not in ('relevance','followers','engagement','price') then raise exception 'unknown sort: %', sort_by using errcode = '22023'; end if;`, then `return query` the M3 select with every column qualified. Ordering:
  ```sql
  order by
    case when sort_by = 'followers' then c.followers end desc nulls last,
    case when sort_by = 'engagement' then c.engagement_rate end desc nulls last,
    case when sort_by = 'price' then cheapest.price end asc nulls last,
    distance nulls last, c.followers desc, c.id
  ```
  where `cheapest.price` is a lateral `min(p.base_price_cents)` over published packages passing the price and content-type filters. Keep `security invoker`, `set search_path = ''`, and re-issue `revoke execute … from public, anon, authenticated`.
- [ ] **Step 5: Ask the user to approve applying the migration to the hosted database**, then run `cd backend; uv run python -m scripts.apply_migration supabase/migrations/20261108120000_voice_session.sql`.
- [ ] **Step 6: Run to verify they pass**
  Run: `cd backend; uv run pytest -q tests/db`
  Expected: PASS, including every existing `test_match_creators` test.
- [ ] **Step 7: Commit** `feat(db): campaign name, confirmed hire target and search sort`

### Task 2: Search sort through the API

**Files:**
- Modify: `backend/app/schemas/discovery.py`, `backend/app/modules/discovery/repo.py:18-87`, `backend/app/modules/discovery/service.py:48-54`
- Test: `backend/tests/api/test_discovery.py`

**Interfaces:**
- Consumes: Task 1's `sort_by` parameter.
- Produces: `SearchSort = Literal["relevance", "followers", "engagement", "price"]` in `app/schemas/discovery.py`; `SearchRequest.sort: SearchSort | None = None`; `repo.match_creator_ids(..., sort: SearchSort | None = None)`. `SearchResponse` echoes the request including `sort` (add `sort: SearchSort | None = None` to `SearchResponse`).

- [ ] **Step 1: Write the failing tests**
  - `test_sort_engagement_orders_by_engagement`: POST `{"sort": "engagement"}` → `results` engagement rates are non-increasing (nulls last).
  - `test_sort_is_echoed`: response `sort == "price"` for a price request; `None` when omitted.
  - `test_unknown_sort_is_422`: `{"sort": "random"}` → 422.
- [ ] **Step 2: Run to verify they fail** — `cd backend; uv run pytest -q tests/api/test_discovery.py` → new tests FAIL.
- [ ] **Step 3: Implement** the schema field, add `sort_by => $9` to `MATCH_CREATORS`, pass `req.sort` from `DiscoveryService.search`, echo it in `SearchResponse`.
- [ ] **Step 4: Run to verify they pass** — same command → PASS (all of `test_discovery.py`).
- [ ] **Step 5: Regenerate API types** — `cd frontend; npm run api:gen`; `npm run typecheck` → no errors.
- [ ] **Step 6: Commit** `feat(discovery): sort by relevance, followers, engagement or price`

### Task 3: Brief rules

**Files:**
- Modify: `backend/app/schemas/briefs.py:19-55`, `backend/app/core/brief_rules.py`
- Test: `backend/tests/core/test_brief_rules.py`

**Interfaces:**
- Produces:
  - `BriefFields.campaign_name: str | None = None` (validator: strip; blank → `None`).
  - `REQUIRED_BRIEF_FIELDS` gains `"hires_target"` after `"flexibility"`.
  - `BRIEF_FIELD_LABELS` gains `"campaign_name": "campaign name"`, `"hires_target": "creators to hire"`.
  - `field_error("campaign_name", value, today)` → `"Keep the campaign name to 80 characters."` when `len > 80`.
  - `violations(brief, today, creator_count: int | None = None)` and `is_launchable(brief, today, creator_count: int | None = None)`: when both `brief.hires_target` and `creator_count` are set and `hires_target > creator_count`, add `RuleViolation(field="hires_target", message="You picked fewer creators than you want to hire.")`.

- [ ] **Step 1: Write the failing tests**
  - `test_hires_target_is_required`: a brief with every other required field and `hires_target=None` → `missing_fields == ["hires_target"]`.
  - `test_campaign_name_over_80_is_an_error`, `test_campaign_name_is_not_required`.
  - `test_more_hires_than_creators_is_a_violation`: `hires_target=3, creator_count=2` → one violation with the exact message; `creator_count=None` → none.
- [ ] **Step 2: Run to verify they fail** — `cd backend; uv run pytest -q tests/core/test_brief_rules.py` → FAIL.
- [ ] **Step 3: Implement** the schema and rule changes above.
- [ ] **Step 4: Run to verify they pass** — same command → PASS.
- [ ] **Step 5: Commit** `feat(briefs): campaign name and a required hire target in the brief rules`

### Task 4: Brief service — confirmed hire target, creators on a draft, campaign name

**Files:**
- Modify: `backend/app/schemas/briefs.py:57-92`, `backend/app/modules/briefs/service.py:94-190,243-310`, `backend/app/modules/briefs/repo.py:64-76`, `backend/app/modules/briefs/voice_session.py:15-40`
- Test: `backend/tests/api/test_briefs.py`, `test_launch.py`, `test_brief_voice_session.py`, `test_m3_privacy.py`

**Interfaces:**
- Consumes: Task 3's rules (`violations`/`is_launchable` with `creator_count`).
- Produces:
  - `BriefPatch.creator_ids: list[UUID] | None = Field(None, min_length=1, max_length=10)`.
  - `DealBrief.hires_target: int | None` (`None` while `hires_target_confirmed` is false).
  - `repo.SELECT_BRIEF` also selects `b.hires_target_confirmed`; `PATCHABLE` adds `"creator_ids"`, `"hires_target_confirmed"`.
  - `_fields(row)` sets `hires_target=None` when `not row["hires_target_confirmed"]`; `_deal_brief` passes `creator_count=len(row["creator_ids"])` to the rules.
  - `BriefService.patch`: a sent `hires_target` value stores it with `hires_target_confirmed=True`; a sent `null` stores `1` with `hires_target_confirmed=False`. Sent `creator_ids` are de-duplicated in order and checked with `repo.listed_creator_ids` (unknown → `UnknownCreators`, the router's existing 422). Launched → `BriefLaunched` (409) as today.
  - `brief_dynamic_variables`: `missing_fields` excludes `hires_target`.

- [ ] **Step 1: Write the failing tests**
  - `test_briefs.py::test_new_brief_has_no_hire_target_and_lists_it_missing`: POST `/briefs` → `hires_target is None`, `"hires_target" in missing`.
  - `test_briefs.py::test_patch_hires_target` (update the existing test): PATCH `{"hires_target": 2}` → `2`; PATCH `{"hires_target": null}` → `None` and missing again.
  - `test_briefs.py::test_patch_creator_ids_replaces_the_list_in_order`: PATCH `[b, a, b]` → `creator_ids == [b, a]`; the preview lists `b, a`.
  - `test_briefs.py::test_patch_creator_ids_rejects_unknown` → 422; `test_patch_creator_ids_empty_is_422`.
  - `test_briefs.py::test_patch_creator_ids_after_launch_409`.
  - `test_briefs.py::test_campaign_name_round_trips_and_trims`: `"  March launch "` → `"March launch"`.
  - `test_launch.py::test_unconfirmed_hire_target_blocks_launch`: a complete brief without a confirmed target → launch 422 naming `hires_target`.
  - `test_brief_voice_session.py::test_agent_missing_fields_leave_out_the_hire_target`.
  - `test_m3_privacy.py::test_campaign_name_never_reaches_creators`: set `campaign_name="SENTINEL-CAMPAIGN"`, launch to a fictional creator, and assert the sentinel is absent from every creator-facing payload the sweep already collects (outreach email, call variables, creator offers and deals responses).
- [ ] **Step 2: Run to verify they fail** — `cd backend; uv run pytest -q tests/api/test_briefs.py tests/api/test_launch.py tests/api/test_brief_voice_session.py tests/api/test_m3_privacy.py` → new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above. Fix any existing test that relied on `hires_target` defaulting to 1 by patching it explicitly in its setup (e.g. `tests/api/helpers.py` complete-brief helpers).
- [ ] **Step 4: Run the whole backend suite** — `cd backend; uv run pytest -q` → PASS.
- [ ] **Step 5: Regenerate API types** — `cd frontend; npm run api:gen; npm run typecheck`. Fix type errors caused by `hires_target: number | null` in `app/brand/briefs/[id]/page.tsx` by passing the value straight to `Stepper` (it accepts `null`) with `emptyText="—"`; `npm test` → PASS.
- [ ] **Step 6: Commit** `feat(briefs): confirmed hire target, editable creators on a draft, campaign name`

### Task 5: Campaign name on the board

**Files:**
- Modify: `backend/app/schemas/board.py:99-135`, `backend/app/modules/board/repo.py:20-40`, `backend/app/modules/board/service.py:180-195`, `frontend/app/brand/batches/[id]/page.tsx:349-352`, `frontend/app/brand/batches/page.tsx`
- Test: `backend/tests/api/test_board.py`, `frontend/tests/unit/board-page.test.tsx`, `frontend/tests/unit/batches-page.test.tsx`

**Interfaces:**
- Produces: `BriefSummary.campaign_name: str | None` and the batch-list row's `campaign_name: str | None`; the board heading shows `campaign_name ?? product_name`.

- [ ] **Step 1: Write the failing tests**: `test_board.py::test_board_brief_carries_campaign_name`; `board-page.test.tsx` "heads the board with the campaign name, else the product"; the same for the batches list row.
- [ ] **Step 2: Run to verify they fail** — `cd backend; uv run pytest -q tests/api/test_board.py`; `cd frontend; npx vitest run tests/unit/board-page.test.tsx tests/unit/batches-page.test.tsx` → FAIL.
- [ ] **Step 3: Implement**: select `br.campaign_name` in both queries, add the fields, run `npm run api:gen`, render the heading.
- [ ] **Step 4: Run to verify they pass** — same commands → PASS.
- [ ] **Step 5: Commit** `feat(board): campaign name in the board and launches headings`

### Task 6: Session voice schemas and prompt

**Files:**
- Modify: `backend/app/schemas/voice.py`, `backend/app/modules/voice/prompts.py`, `backend/app/modules/voice/service.py:33-54`
- Test: `backend/tests/core/test_voice_service.py`

**Interfaces:**
- Consumes: `SearchSort`, `SearchFilters`, `SearchText` (Task 2), `Flexibility` (`schemas/briefs.py`), `ContentType`.
- Produces (all in `app/schemas/voice.py`):
  ```python
  SearchDimension = Literal["query", "niches", "content_types", "max_price", "min_followers", "region"]
  class SessionSearch(BaseModel):
      mode: Literal["refine", "new"] = "refine"
      query: SearchText = None
      filters: SearchFilters = Field(default_factory=SearchFilters)
      clear: list[SearchDimension] = []
      sort: SearchSort | None = None
  class SessionBrief(BaseModel):  # every field optional; only what was said
      campaign_name: str | None = None
      hires_target: int | None = Field(None, ge=1, le=10)
      deliverables_count: int | None = Field(None, ge=1)
      deliverables_format: ContentType | None = None
      go_live_by: date | None = None
      budget_ceiling_cents: int | None = Field(None, ge=1)
      ask_price_cents: int | None = Field(None, ge=1)
      negotiation_ask: str | None = None
      flexibility: list[Flexibility] = []
  class RoutedSwap(BaseModel): out_name: str; replacement: SessionSearch
  class RoutedSession(BaseModel):
      brief: SessionBrief | None = None
      go_live_hint: str | None = None
      search: SessionSearch | None = None
      remove_names: list[str] = []
      add_names: list[str] = []
      swap: RoutedSwap | None = None
      top_n: int | None = Field(None, ge=1, le=10)
      top_n_mode: Literal["replace", "add"] = "replace"
  class SessionSwap(BaseModel): out_id: UUID; replacement: SessionSearch
  class RejectedField(BaseModel): field: str; message: str
  class SessionCommand(BaseModel):
      brief: SessionBrief | None = None
      go_live_hint: str | None = None
      search: SessionSearch | None = None
      remove_ids: list[UUID] = []
      add_ids: list[UUID] = []
      swap: SessionSwap | None = None
      top_n: int | None = None
      top_n_mode: Literal["replace", "add"] = "replace"
      rejected: list[RejectedField] = []
      skipped: list[str] = []
  class SessionBriefStatus(BaseModel):
      filled: list[str] = []
      missing: list[str] = []
      campaign_name: str | None = None
  ```
  `IntentKind` gains `"session"`; `RoutedIntent.session: RoutedSession | None = None`; `VoiceIntent.session: SessionCommand | None = None`; `VoiceContext` gains `current_search: SearchRequest | None = None`, `shortlist: list[CreatorRef] = []`, `brief_status: SessionBriefStatus | None = None`; `ALLOWED_INTENTS["discover"] = {"session", "clear_selection", "open_review", "navigate"}`.
  `DEFAULT_SUGGESTIONS["discover"] = ["Find three fitness creators under two thousand dollars each", "Swap the second one for someone who does home workouts", "Go live on March 31"]`.

- [ ] **Step 1: Write the failing tests** in `test_voice_service.py`:
  - `test_discover_allows_session_not_search`: a routed `search` on `discover` → `unclear`.
  - `test_router_prompt_lists_search_shortlist_and_brief_status`: `router_prompt` output contains `Current search:` with the query and filters JSON, `Shortlist: Meera Nair (@…)`, `Brief filled: budget_ceiling_cents`, `Brief missing: go_live_by`, and never a cents value from the brief.
  - `test_system_prompt_states_session_rules`: `ROUTER_SYSTEM` contains `go_live_hint`, `"each"`, `top_n_mode` and the sentence "Never put a month, season or event in go_live_by."
- [ ] **Step 2: Run to verify they fail** — `cd backend; uv run pytest -q tests/core/test_voice_service.py` → FAIL.
- [ ] **Step 3: Implement** the models; add a `- session:` paragraph to `ROUTER_SYSTEM` stating spec §3.1's four parts and prompt rules (including "Never put a month, season or event in go_live_by."); extend `router_prompt` with `Current search: <json or none>`, `Shortlist: <name (@handle); …>`, `Brief filled: <names>`, `Brief missing: <names>`, `Campaign: <name or none>`. Update the existing `discover` tests in `test_voice_service.py` and `tests/api/test_voice.py` that expected `search`/`select` on `discover` to use `review`.
- [ ] **Step 4: Run to verify they pass** — `cd backend; uv run pytest -q tests/core/test_voice_service.py tests/api/test_voice.py` → PASS.
- [ ] **Step 5: Commit** `feat(voice): session command schema, context and prompt rules`

### Task 7: Session command in the router service

**Files:**
- Modify: `backend/app/modules/voice/service.py:99-160`
- Test: `backend/tests/core/test_voice_service.py`, `backend/tests/api/test_voice.py`

**Interfaces:**
- Consumes: Task 6 models; `resolve_creator_refs(names, visible) -> list[UUID]` (`app/core/refs.py`); `brief_rules.field_error`.
- Produces: `_session(req: VoiceCommandRequest, routed: RoutedSession, today: date) -> SessionCommand | None` (None = nothing usable → caller returns `unclear`). `_to_intent` gains `case "session" if routed.session is not None`. `route` passes `today` through to `_to_intent`.
  - Names: each of `remove_names`/`add_names` resolved one at a time against `shortlist + visible_creators` (dedupe by id); `swap.out_name` against `shortlist` only. Unmatched names go to `skipped` as said.
  - Brief: each field set on `SessionBrief` (non-null; `flexibility` non-empty) checked with `field_error(name, value, today)`; failures removed and added to `rejected` with the message; the rest kept.
  - Usable when any of: kept brief field, `go_live_hint`, `search`, `remove_ids`, `add_ids`, `swap`, `top_n`.

- [ ] **Step 1: Write the failing tests** (FakeGemini `queue_structured`, `today=date(2026, 11, 8)`):
  - `test_session_resolves_names_against_shortlist_and_visible`: remove "meera" (shortlist) and add "Jordan" (visible) → ids.
  - `test_swap_out_name_not_on_the_shortlist_is_skipped`: swap out "Callum" who is only visible → `swap is None`, `skipped == ["Callum"]`.
  - `test_past_go_live_is_rejected_and_the_rest_kept`: brief `{go_live_by: 2026-01-01, budget_ceiling_cents: 200000}` → `brief.go_live_by is None`, `budget_ceiling_cents == 200000`, `rejected == [{"field": "go_live_by", "message": "The go-live date must be in the future."}]`.
  - `test_session_with_nothing_usable_is_unclear`.
  - `test_session_passes_search_and_top_n_through`: `search.mode == "refine"`, `top_n == 3`, `top_n_mode == "replace"`.
  - `tests/api/test_voice.py::test_session_intent_round_trips`: POST with `shortlist`, `current_search`, `brief_status` in context → 200 and `kind == "session"`.
- [ ] **Step 2: Run to verify they fail** — `cd backend; uv run pytest -q tests/core/test_voice_service.py tests/api/test_voice.py` → FAIL.
- [ ] **Step 3: Implement** `_session` and the `_to_intent` case.
- [ ] **Step 4: Run to verify they pass** — same command → PASS; then `uv run pytest -q` → PASS.
- [ ] **Step 5: Regenerate API types** — `cd frontend; npm run api:gen; npm run typecheck` → no errors (`IntentKind` only gained `session`; Discover starts handling it in Task 13).
- [ ] **Step 6: Commit** `feat(voice): route session commands with name resolution and per-field checks`

### Task 8: Live router evals

**Files:**
- Modify: `backend/tests/live/test_intent_live.py`

**Interfaces:**
- Consumes: the real router via the file's existing `settings` fixture pattern; screen `discover`; visible creators from the seed (`Meera Nair`, `Jordan Blake`, `Callum Reid`).

- [ ] **Step 1: Write the live tests** (`@pytest.mark.live`, `today=date(2026, 11, 8)`):
  - `test_sample_request`: "Find three fitness creators for our March launch. Keep each under two thousand dollars." → `kind == "session"`, `search.filters.niches == ["fitness"]`, `search.filters.max_price_cents == 200000`, `top_n == 3`, `brief.budget_ceiling_cents == 200000`, `brief.campaign_name` contains "March", `brief.go_live_by is None`, `"march" in go_live_hint.lower()`, `brief.hires_target is None`.
  - `test_swap_by_name`: shortlist `[Meera Nair, Jordan Blake]`, "Swap Meera for someone who does home workouts" → `swap.out_id == meera`, `"home" in swap.replacement.query`.
  - `test_refine_price_keeps_mode_refine`: current search fitness under $2,000; "make it under fifteen hundred" → `mode == "refine"`, `max_price_cents == 150000`, `niches` empty or `["fitness"]`.
  - `test_drop_price_limit`: → `"max_price" in search.clear`.
  - `test_several_fields_at_once`: "one short video each, go live March 31 2027, open at twelve hundred, flexible on timeline" → `deliverables_count == 1`, `deliverables_format == "short_video"`, `go_live_by == date(2027, 3, 31)`, `ask_price_cents == 120000`, `flexibility == ["timeline"]`.
  - `test_three_more_adds`: "three more" → `top_n == 3`, `top_n_mode == "add"`.
  - `test_hire_all_three`: shortlist of 3, "we'll hire all three" → `brief.hires_target == 3`.
- [ ] **Step 2: Run** — `cd backend; uv run pytest -m live tests/live/test_intent_live.py -k "sample or swap or refine or drop or several or more or hire" -q`
  Expected: PASS. A failure means the prompt from Task 6 needs a clearer rule; adjust `ROUTER_SYSTEM` (not the assertions) and re-run, then re-run Task 6/7 tests.
- [ ] **Step 3: Commit** `test(voice): live evals for the session command`

### Task 9: Session state reducers (frontend)

**Files:**
- Create: `frontend/lib/session/state.ts`
- Test: `frontend/tests/unit/session-state.test.ts`

**Interfaces:**
- Consumes: `components["schemas"]` types `SessionSearch`, `SessionBrief`, `SearchSort`, `BriefPatch`; `normalizeFilters`, `MAX_SELECTED`, `SEARCH_LIMIT`, `CreatorCard`, `SearchFilters`, `SearchRequest` from `lib/discover/state.ts`.
- Produces:
  ```ts
  export type SessionSearchState = { query: string | null; filters: SearchFilters; sort: SearchSort | null }
  export const emptySessionSearch: SessionSearchState
  export function mergeSearch(current: SessionSearchState, said: SessionSearch): SessionSearchState
  export function sessionRequest(search: SessionSearchState): SearchRequest   // limit SEARCH_LIMIT
  export function swapInPlace(shortlist: string[], outId: string, results: CreatorCard[]): { shortlist: string[]; inId: string | null }
  export function pick(shortlist: string[], results: CreatorCard[], n: number, mode: "replace" | "add"): { shortlist: string[]; added: string[]; overflow: boolean }
  export function removeIds(shortlist: string[], ids: string[]): string[]
  export function addIds(shortlist: string[], ids: string[]): { shortlist: string[]; overflow: boolean }
  export function briefPatchFrom(said: SessionBrief): BriefPatch   // only fields that were said
  /** `briefId` lets Review and the brief page link back to the request. */
  export type StoredSession = { briefId: string | null; pending: BriefPatch; goLiveHint: string | null }
  export const SESSION_KEY = "collabio:session"
  export function loadSession(): StoredSession
  export function saveSession(s: StoredSession): void   // try/catch like lib/discover/state.ts
  ```

- [ ] **Step 1: Write the failing tests**
  - `mergeSearch keeps unmentioned filters`: current `{niches:["fitness"], max_price_cents:200000}`, said `{filters:{max_price_cents:150000}}` → `{niches:["fitness"], max_price_cents:150000}`.
  - `mergeSearch clears named dimensions`: `clear:["max_price"]` → no `max_price_cents`; `clear:["query"]` → `query: null`.
  - `mergeSearch mode new starts empty`: said `{mode:"new", filters:{niches:["beauty"]}}` → only beauty, `sort` from said or null.
  - `mergeSearch keeps the current sort unless one is said`.
  - `swapInPlace puts the first new result in the out creator's place`: `["a","b","c"]`, out `b`, results `[a, c, d, e]` → `["a","d","c"]`, `inId:"d"`.
  - `swapInPlace with no new result keeps the list`: results `[a, c]` → unchanged, `inId:null`.
  - `pick takes what exists`: n=3, results of 2 → shortlist of 2.
  - `pick add appends without duplicates and respects the cap`: 9 picked + add 3 → 10, `overflow: true`.
  - `briefPatchFrom drops unsaid fields`: `{budget_ceiling_cents:200000, flexibility:[]}` → `{budget_ceiling_cents:200000}`.
  - `loadSession survives broken storage`: `sessionStorage.getItem` throws → `{briefId:null, pending:{}, goLiveHint:null}`.
- [ ] **Step 2: Run to verify they fail** — `cd frontend; npx vitest run tests/unit/session-state.test.ts` → FAIL.
- [ ] **Step 3: Implement** `lib/session/state.ts`.
- [ ] **Step 4: Run to verify they pass** — same → PASS.
- [ ] **Step 5: Commit** `feat(session): pure session state and reducers`

### Task 10: Summary line, sheet model and brief field labels

**Files:**
- Create: `frontend/lib/session/summary.ts`, `frontend/lib/session/sheet.ts`
- Modify: `frontend/lib/brief/state.ts` (add `"campaign_name"` to `BriefFieldKey`, `BRIEF_FIELDS` row `{ key: "campaign_name", label: "Campaign", required: false }` first, `MISSING_LABELS` `campaign_name: "campaign name"`, `hires_target: "creators to hire"`), `frontend/components/brief/field-editor.tsx` (`KINDS.campaign_name = "text"`)
- Test: `frontend/tests/unit/session-summary.test.ts`, `frontend/tests/unit/session-sheet.test.ts`, `frontend/tests/unit/brief-state.test.ts`

**Interfaces:**
- Consumes: `formatCents`, `MISSING_LABELS`, `DealBrief`, `BriefCreatorPreview` types, `SearchSort`.
- Produces:
  ```ts
  // summary.ts
  export type SessionOutcome = {
    heard: string
    rejected: { field: string; message: string }[]
    search: { count: number; maxPriceCents: number | null; sort: SearchSort | null } | null
    picked: { taken: number; of: number } | null
    swapped: { out: string; in: string | null; underCap: boolean | null; description: string } | null
    removed: string[]; added: string[]
    noted: string[]          // e.g. ["budget cap $2,000", "campaign “March launch”"]
    skipped: string[]
  }
  export function summarize(o: SessionOutcome): string
  // sheet.ts
  export type SheetFieldKey = "campaign_name" | "hires_target" | "deliverables" | "go_live_by" | "budget_ceiling_cents" | "ask_price_cents" | "negotiation_ask" | "flexibility"
  export type SheetRow = { key: SheetFieldKey; label: string; answered: boolean; value: string | null; question: string; fromVoice: boolean; optional: boolean }
  export function sheetRows(brief: DealBrief, creatorCount: number, goLiveHint: string | null, fromVoice: ReadonlySet<string>): SheetRow[]
  export function sheetTitle(brief: DealBrief, preview: readonly BriefCreatorPreview[]): string
  export function mostYoudSpend(brief: DealBrief): number | null   // budget_ceiling_cents × hires_target
  export function approveLocks(brief: DealBrief, preview: readonly BriefCreatorPreview[], synced: boolean): string[]
  ```

- [ ] **Step 1: Write the failing summary tests** (exact strings; parts joined with " · ", at most two parts, priority: rejected → search/pick → swap/remove/add → noted → skipped; fallback `Heard: “{heard}”`):
  - search + pick: `Picked the top 3 of 24 matches under $2,000, sorted by engagement`
  - search only, no sort/price: `Found 24 matches`
  - pick short: `Picked the top 2 of 2 matches`
  - swap: `Swapped Meera Nair for Divya Shah · still under your cap`
  - swap kept: `No match for “home workouts” under your filters; kept Meera Nair`
  - rejected first: `Couldn't use the go-live date: The go-live date must be in the future.`
  - noted only: `Noted: budget cap $2,000, campaign “March launch”`
  - skipped: `Couldn't find Callum on your shortlist`
  - two-part cap: rejected + search + noted → only the first two parts appear.
  - nothing: `Heard: “um okay”`
- [ ] **Step 2: Write the failing sheet tests**
  - `sheetRows` order matches spec §2 table; questions exact: `Name this campaign? (optional)`, `How many of these 3 do you want to hire?`, `How many videos each, in what format?`, `Go-live date? (you said March)` (without hint: `Go-live date?`), `Most you'll pay per creator? (private)`, `Opening offer per creator?`, `What should we negotiate for?`, `Where are you flexible?`.
  - `deliverables` answered only when both count and format are set; value `1 × Short video`.
  - `sheetTitle`: `Start 3 negotiations · listed total $5,800 · Brief: March launch`; singular `Start 1 negotiation`; product fallback `Brief: Lumen Pods`; with one excluded: `Start 2 negotiations · listed total $3,900 · Brief: March launch · 1 can't be contacted` (total counts reachable only).
  - `mostYoudSpend`: ceiling 200000 × hires 2 → 400000; either missing → null.
  - `approveLocks`: missing → `Still needed: go-live date, creators to hire`; violations' messages; `No creators can be contacted.`; not synced → `Saving your shortlist…`; all fine → `[]`.
  - `brief-state.test.ts`: `missingLabels(["hires_target"])` → `["creators to hire"]`; `BRIEF_FIELDS[0].key === "campaign_name"`.
- [ ] **Step 3: Run to verify they fail** — `cd frontend; npx vitest run tests/unit/session-summary.test.ts tests/unit/session-sheet.test.ts tests/unit/brief-state.test.ts` → FAIL.
- [ ] **Step 4: Implement** `summary.ts`, `sheet.ts` and the brief-state/field-editor additions. `approveLocks` reuses the "Still needed:" format of `components/brief/launch-bar.tsx`'s `lockReasons` (move that function into `lib/brief/state.ts` as `launchLockReasons(count, missing, violations)` and import it from both).
- [ ] **Step 5: Run to verify they pass** — same, plus `npx vitest run tests/unit/brief-card.test.tsx tests/unit/brief-page.test.tsx` → PASS (update a brief-card test that counts rows, if any, for the new Campaign row).
- [ ] **Step 6: Commit** `feat(session): summary line and confirm-sheet model`

### Task 11: Draft brief sync hook

**Files:**
- Create: `frontend/hooks/use-session-brief.ts`
- Test: `frontend/tests/unit/use-session-brief.test.tsx`

**Interfaces:**
- Consumes: `useApi()` (`POST /api/v1/briefs`, `GET/PATCH /api/v1/briefs/{brief_id}`, `GET /api/v1/briefs/{brief_id}/preview`, `POST /api/v1/briefs/{brief_id}/launch`); `loadSession`/`saveSession` (Task 9); `invalidFieldMessage` (`lib/brief/state.ts`).
- Produces:
  ```ts
  // Named SessionDraft: `SessionBrief` is the API schema for brief fields in a voice command.
  export type SessionDraft = {
    briefId: string | null
    brief: DealBrief | null
    preview: BriefCreatorPreview[]
    synced: boolean
    syncError: boolean
    /** The server should hold exactly these creators. [] detaches the draft (briefId → null). */
    syncCreators(ids: string[]): Promise<void>
    /** Saves fields; before a draft exists they are kept as pending. Returns an error message or null. */
    patch(fields: BriefPatch): Promise<string | null>
    retry(): void
    launch(): Promise<{ batchId: string } | { error: string }>
  }
  export function useSessionBrief(initialBriefId: string | null, opts: { onGone(): void; onLaunched(batchId: string): void }): SessionDraft
  ```
  Launch body: `channels` = each reachable preview creator's `default_channel`; `follow_up_policy: "suggest"`. The hook writes `briefId` into `StoredSession` (Task 9) whenever it changes.

- [ ] **Step 1: Write the failing tests** (mock `useApi` as in `tests/unit/brief-page.test.tsx`):
  - `creates the draft on the first sync and sends pending fields after create`: `patch({budget_ceiling_cents:200000})` with no draft → no API call, stored in `SESSION_KEY`; `syncCreators(["a"])` → POST `/briefs {creator_ids:["a"]}` then PATCH `{budget_ceiling_cents:200000}`; storage pending cleared.
  - `pending fields survive a reload and go out after create`: seed `SESSION_KEY` with pending, mount, `syncCreators(["a"])` → PATCH carries them.
  - `later syncs PATCH creator_ids`.
  - `an older reply does not mark a newer shortlist synced`: `syncCreators(["a","b"])` (slow) then `syncCreators(["a"])` (fast); the fast resolves first, then the slow one → `synced` true only if the server's `creator_ids` equal `["a"]`; after the slow reply returns `["a","b"]`, `synced` is false and a re-PATCH of `["a"]` is sent.
  - `a failed PATCH leaves synced false and retry resends`.
  - `an unknown initial brief calls onGone`: GET 404 → `onGone`, `briefId` null.
  - `a launched initial brief calls onLaunched` with its `batch_id`.
  - `syncCreators([]) detaches`: `briefId` null, no API call, stored `briefId` null.
  - `stores the brief id`: after create, `loadSession().briefId` is the new id.
  - `launch posts default channels and suggest`: body matches; 409 → refreshes and calls `onLaunched` when the refreshed brief has a batch.
- [ ] **Step 2: Run to verify they fail** — `cd frontend; npx vitest run tests/unit/use-session-brief.test.tsx` → FAIL.
- [ ] **Step 3: Implement** the hook. Keep a request counter per sync like `previewRequest` in `app/brand/briefs/[id]/page.tsx`; `synced = !inFlight && equal(server.creator_ids, wanted)`. Refresh the preview after every successful PATCH or create.
- [ ] **Step 4: Run to verify they pass** — same → PASS.
- [ ] **Step 5: Commit** `feat(session): keep the draft brief in step with the shortlist`

### Task 12: Session components

**Files:**
- Create: `frontend/components/session/summary-line.tsx`, `shortlist.tsx`, `confirm-sheet.tsx`
- Test: `frontend/tests/unit/session-components.test.tsx`

**Interfaces:**
- Consumes: Task 10 (`sheetRows`, `sheetTitle`, `mostYoudSpend`, `approveLocks`), `FieldEditor` (`components/brief/field-editor.tsx`), `Stepper`, `CreatorAvatar`, `formatFollowers`, `formatEngagement`, `formatCents`.
- Produces:
  ```ts
  export function SummaryLine(props: { text: string | null }): JSX.Element | null   // role="status", ✦ icon
  export type ShortlistRow = { creator: CreatorCard; priceCents: number | null; niche: string; updated: boolean; excludedReason: string | null }
  export function Shortlist(props: { rows: ShortlistRow[]; onRemove(id: string): void }): JSX.Element | null
  export function ConfirmSheet(props: {
    brief: DealBrief; preview: BriefCreatorPreview[]; synced: boolean; goLiveHint: string | null; fromVoice: ReadonlySet<string>
    onPatch(patch: BriefPatch): Promise<string | null>; onEdit(): void; onCompare(): void; onApprove(): void; approving: boolean
  }): JSX.Element
  ```
  Shortlist: `role="list" aria-label="Your shortlist"`; an updated row has `data-updated="true"`, a visible "Updated" badge and an outline; no motion under `prefers-reduced-motion` (follow the `gsap.matchMedia` pattern in `components/deal/selection-tray.tsx`). Sheet: `role="region" aria-label="Confirm your request"`; question rows render the question text and an "Answer" button opening the editor; `hires_target` uses `Stepper` (min 1, max creator count); `deliverables` opens count then format editors; "Approve & send" is disabled with the lock reasons in a tooltip (same pattern as `LaunchBar`); "Most you'd spend: $4,000" appears when `mostYoudSpend` is not null; a "From your profile" line shows product and contact email; a contact-plan line reads `Email first · change in Edit` when every reachable creator's `default_channel` is `email`, otherwise `Email, then a call where allowed · change in Edit`.

- [ ] **Step 1: Write the failing tests**
  - `summary line announces the text`; renders nothing for null.
  - `shortlist marks the updated row` (`data-updated`, "Updated" text) and shows `$1,900` and `96k · 7.4%`.
  - `sheet shows the title, questions and locks`: given a brief missing `go_live_by` and `hires_target`, the region contains the exact title, `Go-live date? (you said March)`, and "Approve & send" is disabled.
  - `answering a question patches the brief`: open "Go-live date?", type `2027-03-31`, Save → `onPatch({go_live_by:"2027-03-31"})`.
  - `hire stepper patches hires_target`.
  - `approve is enabled only when complete and synced` and calls `onApprove`; `synced=false` keeps it disabled with `Saving your shortlist…`.
  - `voice-filled values carry the marker`: `fromVoice` containing `budget_ceiling_cents` → that row shows "from what you said".
- [ ] **Step 2: Run to verify they fail** — `cd frontend; npx vitest run tests/unit/session-components.test.tsx` → FAIL.
- [ ] **Step 3: Implement** the three components.
- [ ] **Step 4: Run to verify they pass** — same → PASS.
- [ ] **Step 5: Commit** `feat(session): summary line, shortlist and confirm sheet components`

### Task 13: Discover becomes the session

**Files:**
- Modify: `frontend/app/brand/discover/page.tsx`, `frontend/lib/discover/state.ts` (`SearchInput`/`saveSearch`/`loadSearch` carry `sort`)
- Test: `frontend/tests/unit/discover-page.test.tsx`, `frontend/tests/unit/discover-state.test.ts`

**Interfaces:**
- Consumes: Tasks 9–12; `useVoiceScreen("discover", getContext, onIntent)`; `useSearchParams` / `useRouter` (read the Next 16 docs first).
- Produces: the page behaviour of spec §2 and §3.4:
  - Context: `visible_creators` (results), `shortlist` (`CreatorRef[]` in order), `current_search` (`sessionRequest(search)`), `brief_status` (`{filled, missing, campaign_name}` from the brief, or from pending fields when there is no draft).
  - `onIntent` for `session` runs `apply(command)` through a promise queue so commands apply one at a time, in spec order: brief → search → remove → add → swap → pick → `syncCreators` → `summarize`.
  - `clear_selection` → shortlist `[]`, `syncCreators([])`, URL drops `brief`. `open_review` → `saveSelection(shortlist)`, push Review.
  - Card toggles and shortlist removals go through the same `syncCreators`.
  - The URL is `?brief=<id>` whenever a draft exists (`router.replace`).
  - Shortlist row price: the preview package's `base_price_cents` when the draft is synced, else `bestFitPackage(card.packages, filters)`.
  - `SelectionTray` is no longer rendered here; `saveSelection(shortlist)` is still called on every change so Review keeps working.
  - Approve → `launch()` → `router.push("/brand/batches/<id>")`; error → toast.

- [ ] **Step 1: Update and write the failing tests** (replace the old `search`/`select` voice tests on this page):
  - `the sample command searches, picks three and notes the cap`: a `session` intent `{search:{filters:{niches:["fitness"], max_price_cents:200000}}, top_n:3, brief:{budget_ceiling_cents:200000, campaign_name:"March launch"}, go_live_hint:"March"}` → POST `/discovery/search` with those filters, POST `/briefs` with the first 3 result ids, PATCH with the cap and campaign, summary `Picked the top 3 of 6 matches under $2,000`, sheet question `Go-live date? (you said March)`, URL `?brief=<id>`.
  - `swap replaces in place and marks Updated`.
  - `refine keeps the niche`: a second command with `max_price_cents:150000` sends both niche and price.
  - `applies session commands one at a time`: two intents delivered back to back while the first search is pending → the second's search request is built from the first's merged state.
  - `card toggle syncs the draft`.
  - `clear empties the shortlist and drops the brief param`.
  - `?brief= of a launched brief goes to its board`; `?brief= unknown starts fresh with a toast`.
  - `approve launches and opens the board`.
  - `discover-state.test.ts`: `loadSearch` keeps a stored `sort`.
- [ ] **Step 2: Run to verify they fail** — `cd frontend; npx vitest run tests/unit/discover-page.test.tsx tests/unit/discover-state.test.ts` → FAIL.
- [ ] **Step 3: Implement** the page. Keep the existing Flip animation, filter chips, empty and error states. Wrap the part that reads `useSearchParams` in a Suspense boundary if the Next 16 docs require it; keep `discover-ssr.test.tsx` passing.
- [ ] **Step 4: Run to verify they pass** — `cd frontend; npm test` → PASS; `npm run typecheck; npm run lint` → clean.
- [ ] **Step 5: Commit** `feat(discover): one-screen voice session with shortlist and confirm sheet`

### Task 14: Review and brief page hand-offs

**Files:**
- Modify: `frontend/app/brand/discover/review/page.tsx:37-52,141-164,229-233`, `frontend/app/brand/briefs/[id]/page.tsx:39,345-356,400-408`
- Test: `frontend/tests/unit/review-page.test.tsx`, `frontend/tests/unit/brief-page.test.tsx`

**Interfaces:**
- Consumes: `loadSession().briefId` (Task 9, written by the Task 11 hook).
- Produces: Review's primary button reads **Back to your request** and links to `/brand/discover?brief=<id>` when a session brief id is stored, otherwise **Start negotiation** as today. The brief page's back link reads **Back to your request** → `/brand/discover?brief=<id>`. The hire stepper passes `emptyText="—"` and `value={brief.hires_target}` (may be null).

- [ ] **Step 1: Write the failing tests**
  - `review offers Back to your request when a session draft exists` (no POST `/briefs` on click).
  - `review still starts a negotiation without a session`.
  - `brief page links back to the request`; `brief page shows — for an unset hire target` and patching sets it.
- [ ] **Step 2: Run to verify they fail** — `cd frontend; npx vitest run tests/unit/review-page.test.tsx tests/unit/brief-page.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify they pass** — `cd frontend; npm test` → PASS.
- [ ] **Step 5: Commit** `feat(session): Review and the brief page lead back to the request`

### Task 15: End-to-end run and full regression

**Files:**
- Create: `frontend/tests/e2e/session.spec.ts`

**Interfaces:**
- Consumes: `signIn`/`newSession`, `say`, `whenHydrated` (`tests/e2e/helpers.ts`); the demo brand and `DEMO_MODE=1` fictional creators, as `m3.spec.ts` uses; the seeded fitness creators. Four have a short video under $2,000 (`Meera Nair` $1,400, `Callum Reid` $750, `Sienna Park` $1,200, `Divya Shah` $1,100); `Jordan Blake` and `Tyler Brooks` do not.

- [ ] **Step 1: Write the spec** `test.describe("Voice session")`, skipped without the demo env vars (same `test.skip` as M3):
  1. Sign in as the brand on `/brand/discover`.
  2. `say(page, "Find three fitness creators for our March launch. Keep each under two thousand dollars.")` → the shortlist region has 3 rows, none of them Jordan Blake or Tyler Brooks; the summary line starts with `Picked the top 3 of 4 matches under $2,000`; the sheet shows `Go-live date? (you said March)`; the URL has `?brief=`.
  3. Read the first shortlist row's first name `X`, then `say(page, "Swap X for someone else")` → that row position now holds the fourth under-$2,000 creator with `data-updated="true"` (the name-agnostic form keeps the test independent of ranking).
  4. `say(page, "One short video each, go live March 31 2027, open at twelve hundred, negotiate for the best price, flexible on timeline, we'll hire one")`.
  5. Answer anything still asked through the sheet's editors; "Approve & send" becomes enabled; click it → URL `**/brand/batches/*`, and the heading matches `/March/` (the campaign name).
  6. Clean up the launched batch the same way `m3.spec.ts` does.
- [ ] **Step 2: Run it** — start the backend with `WORKERS_ENABLED=0` and the frontend dev server as `frontend/README.md` describes, then `cd frontend; npx playwright test tests/e2e/session.spec.ts`. Expected: PASS.
- [ ] **Step 3: Run the full regression**
  - `cd backend; uv run pytest -q` → PASS
  - `cd frontend; npm test; npm run typecheck; npm run lint` → PASS/clean
  - `cd frontend; npx playwright test` (m1, m2, m3, session) → PASS
- [ ] **Step 4: Commit** `test(e2e): the sample voice session from request to board`
- [ ] **Step 5: Report to the user** with the test results. Do not push or merge; the user decides whether `feat/voice-session` merges into `release/next`.

# Collabio M1 — follow-ups for M2

Deferred minor findings and parked items from the M1 task reviews and final whole-branch review (branch `collabio-v1`, commits a1e1ac4..fd06819). None blocks the M1 demo; triage them when planning M2.

## Deferred minor findings (by task)

- **Task 2:** tests load the developer's real backend/.env via cached get_settings (conftest/config.py) — add env isolation fixture when a settings-dependent test appears
- **Task 2:** no committed CORS preflight test (main.py:15-21)
- **Task 2:** secrets default to "" — fail late at first SDK call; consider startup validation
- **Task 4:** merge output shares Addon/Extra instances with inputs (package_rules.py:82)
- **Task 4:** per_video_cents ZeroDivisionError when volume_count==0 (pricing.py:13); PackageTerms lacks ge=1
- **Task 4:** "Niches: " line emitted for empty niches (package_text.py:37)
- **Task 4:** addon/extra blank names not validated (package_rules.py:30-48)
- **Task 4:** rules import display_label from package_text (package_rules.py:3)
- **Task 3:** currency check accepts any ISO code; global constraint is USD-only (migration:86)
- **Task 3:** match_creators orders by distance nulls last — HNSW index unused for ordering (fine at demo scale) (migration:210)
- **Task 3:** config.toml signing_keys_path points to gitignored file; fresh-clone `supabase start` fails (config.toml:169)
- **Task 3:** test_transaction_propagates_errors doesn't assert rollback (test_database.py:37-40)
- **Task 3:** backend/supabase/.gitignore left untracked
- **Task 3:** packages.updated_at has no trigger — Task 10 must set it
- **Task 3:** TLS-phase ConnectionError (OSError subclass) still skips as "not reachable" (tests/db/conftest.py:65)
- **Task 3:** db.py:42-48 pool init failure leaves opened connections unclosed
- **Task 5:** deps.py:85 catches PyJWKClientError (JWKS malformed body) as 401 instead of 503; UUID(sub) parse shares the try
- **Task 5:** service.py:112 deleted auth user with valid token -> unhandled FK violation 500
- **Task 5:** missing API tests: creator same-role repeat, brand repeat keeps contact_email, no-email claim, POST /onboarding without token
- **Task 5:** schemas/me.py:18 comment claims case-insensitive handle uniqueness; DB unique is case-sensitive (seed must use lowercase handles)
- **Task 5:** INSERT_AUTH_USER duplicated in tests/conftest.py and tests/db/conftest.py
- **Task 5:** JWT issuer not verified (deps.py:74-80)
- **Task 6:** google-genai would switch to aiohttp if installed, bypassing retry/wrap (gemini.py:88-96) — pin httpx transport
- **Task 6:** no GeminiError base; callers catch (GeminiUnavailable, GeminiInvalidOutput, ValidationError)
- **Task 6:** GeminiClient('') raises ValueError at construction — T8 get_gemini must construct lazily
- **Task 6:** FakeGemini lacks failure injection; TypeError branch untested (fakes.py:553)
- **Task 6:** offline client tests slow (new client per test)
- **Task 7:** test_seed_dataset.py:26-30 duplicates seed_data helpers; floor assert lacks message
- **Task 7:** build_embedding_cache.py:45 zip not strict
- **Task 7:** seed main catches only SeedError (raw tracebacks for httpx/asyncpg errors)
- **Task 7:** _find_user_id assumes per_page=200 honored
- **Task 7:** seed_marketplace param named `creators` (list) vs ruling's `data`
- **Task 8:** empty GEMINI_API_KEY makes filter-only search 503 gemini_unavailable (deps.py:52-58) — stub port that raises GeminiUnavailable would fix
- **Task 8:** CreatorCard.niches typed list[str] not list[Niche] (schemas/discovery.py:92)
- **Task 8:** PackageTerms built from partial row; extras/included default silently (service.py:72)
- **Task 8:** get_creator module fn vs DiscoveryService.search method style (service.py:56)
- **Task 9:** model suggestions count/content not validated (service.py:83,91)
- **Task 9:** any-screen defaults ignore role (service.py:47)
- **Task 9:** three different 503 details for voice-down (elevenlabs_unavailable / gemini_unavailable / voice_unavailable)
- **Task 9:** schema guard covers only RoutedIntent — extend to Task 10's draft schema
- **Task 9:** VoiceIntent.navigate typed str not NavigateRoute
- **Task 9:** whitespace-only transcript spends a Gemini call
- **Task 9:** spec §4.4 and plan Global Constraints still name gemini-3.8-flash — controller to update docs (Ruling 16)
- **Task 9:** demo emails/phone visible in Settings repr (PII, not credentials)
- **Task 9:** GeminiClient retries daily-quota 429s three times
- **Task 10:** UPSERT_FLOOR/set_floor not scoped by creator_id at SQL level (repo.py:59-62,128-129) — safe via service lock; docstring overclaims
- **Task 10:** PATCH/publish resolve get_gemini eagerly — missing key 503s draft patches/publish (routers/packages.py:98,106)
- **Task 10:** concurrent publishes can store stale embedding (service.py:259-275)
- **Task 10:** packages service imports package_summary from discovery service (move to core)
- **Task 10:** test gaps — floor absence checked on one card not r.text (line 470); unawaited coroutines (521-529); publish updated_at untested; floor PUT statuses unchecked
- **Task 11:** use-api.ts SSR hazard — window.location.replace fallback unguarded on server (use-api.ts:40)
- **Task 11:** no de-dup of concurrent 401 refreshes (client.ts:50)
- **Task 11:** lockfile produced with --legacy-peer-deps; no .npmrc — verify npm ci on fresh clone
- **Task 11:** untested branches (refresh ok but token null; no-router fallback); every request cloned (client.ts:42)
- **Task 12:** dialog.tsx not prettier-formatted (73,125)
- **Task 12:** formatCents silently truncates non-integers / NaN (money.ts:12)
- **Task 12:** SpotlightCard defaults to dark theme surface (carry to T15: pass theme/token overrides)
- **Task 12:** Orb fetches Perlin texture from storage.googleapis.com at runtime; source from GitHub main unpinned (carry to T14: vendor texture to public/)
- **Task 12:** nav active underline uses --voice accent (spec reserves accent for voice; 2.99:1) — final review to triage
- **Task 12:** `num` utility on the word "Soon" (app-shell.tsx:135)
- **Task 13:** updateSession untested (proxy.test mocks it)
- **Task 13:** SessionError outside <main> landmark
- **Task 13:** onboarding-forms.tsx 420 lines — split useOnboard/FormShell
- **Task 13:** NEXT_PUBLIC_DEMO_MODE build-time inlined (not documented in .env.example); persona labels fixed strings
- **Task 14:** mic errors classified by message text only (Firefox no-device not fatal) (use-command-capture.ts:30-48)
- **Task 14:** page getContext() throw shows network message (voice-dock.tsx:141)
- **Task 14:** voice-dock.tsx 466 lines, four jobs — extract usePushToTalk/route
- **Task 14:** stubMotionPreference duplicated in two tests
- **Task 14:** TDD only for reducer; mutation checks substituted
- **Task 15:** Flip matchMedia instances accumulate per search (discover/page.tsx:309-341)
- **Task 15:** empty state doesn't name the query (page.tsx:82-127,382-403)
- **Task 15:** status line pairs new query with old results while loading (page.tsx:240,394)
- **Task 15:** muted package strips opacity-60 likely < 4.5:1 (package-strip.tsx:23) — add to manual visual check
- **Task 15:** Flip test asserts only DOM order; misleading test name in review-page.test.tsx:220
- **Task 15:** filter-chips imports ChipGroup from components/auth
- **Task 15:** Review renders null before hydration (no skeleton)
- **Task 15:** Ruling 21 side effect — popover trigger keeps focus after mouse close (Space reopens popover)
- **Task 16:** Publish gated on client-mirrored violations; client-only "Name every add-on" rule stricter than server (draft.ts:80-124, card:385-389) — make gate depend on missing + server violations, or add backend rule + parity fixture
- **Task 16:** count-up runs on every keystroke in base price input (card:79-80)
- **Task 16:** floor check uses unsaved draft base vs server's saved base (card:267-271)
- **Task 16:** package-draft-card.tsx 785 lines / page.tsx 593 — extract FloorPanel, AnimatedPrice, usePackageEditor
- **Task 16:** duplicated test harness across two test files; weak "only when price changes" assertion
- **Task 16:** new add-on row shows errors before touch; KNOWN_FIELDS duplicates FIELD_LABELS
- **Task 17:** e2e say() uses non-waiting isVisible (m1.spec.ts:127); whenHydrated relies on React private __reactProps$ key (138-145)
- **Task 17:** backend/.env.example comments still describe local supabase start
- **Task 17:** eslint.config.mjs fails prettier --check (npm run format only covers ts/tsx)

## Parked at the final review

- Space during routing window not claimed (voice-dock.tsx:301-302) — Ruling: defer to M2, only on a second Space press while "Working on it".
- .env.example placeholders <password> bypass the [YOUR- guard (config.py:11,54) — Ruling: defer, cosmetic error message.
- spec §4.4 still lists TanStack Query (removed) — Ruling: fix with the M2 spec revision.
- empty readout + thinking orb up to 1.5 s on empty release; dock unmount during commit wait; card shows raw region code — Ruling: defer to M2 polish.

## Notes

- **Task 4:** included/freebies union merge (voice can add, not remove) — accepted; creators remove via click in T16
- **Task 4:** creator_embedding_document callers must pass only published packages (T7/T10)
- **Task 12:** npm audit — 10 high advisories from next/shadcn/eslint-config-next deps (pre-existing scaffold versions) — flag to user
- **Task 13:** brand display_name = company name (accepted); sign-up emailRedirectTo must be in Supabase redirect allow-list (tell user)

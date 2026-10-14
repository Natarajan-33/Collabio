# Collabio M3 — follow-ups

Deferred minor findings and parked items from the M3 task reviews and the final whole-branch review (branch `collabio-m3`, commits 4439453..289957b). None blocks M3. Triage them when planning M4/M5.

## Deferred minor findings

- Task 1: minor (deferred): deferred-trigger delete/update/deal-deleted paths untested; RLS tests accept error-or-zero-rows, no write-refusal test
- Task 1: minor (deferred): apply_migration already-applied check outside txn; raw asyncpg tracebacks on SQL error
- Task 1: minor (deferred): no FK indexes on outbox_emails.thread_id/event_id, deals.batch_id/package_id/awarded_event_id; outbox id seq not revoked
- Task 1: minor (deferred): test_match_creators_registered_only depends on seed; fakes.py has module conv_id vs FakeElevenLabs.conv_id naming overlap
- Tasks 2-4: minor (deferred): strip_reply bottom-posted replies may strip to empty (T11 must treat empty as needs_review — plan already says so); terms_changed flags None-vs-value; html_to_text unclosed <head> drops rest; bare `--` cut
- Tasks 5-6: minor (deferred): compose money guard only rejects literal "$"; brand/product/creator names unsanitised into Gemini prompt (output escaped, capped); RESEND_FROM check after Gemini call; 5-min lease vs sequential batch w/o per-send timeout; vacuous privacy test in compose; creator_awarded w/o deals row degrades silently
- Tasks 7-8: minor (deferred): desk returns full event payloads with no per-type allow-list (email_drafted draft dump, call summary) — whole-branch review should check for leakage; follow_up_suggested visible but in no tab; my_offers onboarding_required string detail; OffersService.list shadows builtin; no API test for ?sort= / non-empty waiting/closed tabs
- Tasks 9-10: minor (deferred): decline-rest preview `skipped` lists terminal threads too; no test for stale_status (StaleThread→409) on a single-thread action
- Tasks 9-10: minor (deferred): decline-rest logs StaleThread races at WARNING (could be noisy); lock-mode change not pinned by a test
- Task 4: minor (deferred): parse_reply_address lives in core/email_quotes.py instead of core/reply_token.py as planned
- Pre-existing: minor (deferred): ruff reports 2 errors in app/modules/voice/try_call.py / try_email.py (from M2 commit dc3f41e) — final review to triage
- Tasks 11-12: minor (deferred, PRIORITY for final triage): email "accept" with conditions/open_questions is stored as plain accept (conditions dropped) — maybe route to needs_review; body-fetch 401/403 (bad Resend key) → 200 ignored silently drops replies — maybe 503
- Tasks 11-12: minor (deferred): email body can close its EMAIL>>> delimiter; full stripped body stored vs 6000 chars to model; expiry loop starvation theoretical; two Resend client instances
- Tasks 13-15: minor (deferred): creator_not_registered uses {code,...} while older launch errors use {error,...} (frontend handles both); Priya has no phone so phone check only exercises Arjun; over-long docstring lines in VoiceService.route / BriefService.launch
- Tasks 13-15: minor (deferred): board router prompt still shows on-screen Current terms (model could echo another creator's date); privacy matcher _LONG_TOKEN scrub could hide an amount glued to a long token; formatted lookbehind excludes amounts after comma
- Pre-existing: minor (deferred): frontend lint error react-hooks/set-state-in-effect in components/voice/try-yourself-dialog.tsx:110 (from M2 commit) + warning in tests/e2e/m1.spec.ts — final triage
- Task 16: minor (deferred): openapi-typescript makes defaulted request fields required (visible_offers) — `as` cast in voice-dock; principled fix `--default-non-nullable false` (whole-branch decision); MilestoneEditor role=alert re-announces per keystroke, no aria-invalid; ExpiryBadge NaN on bad input; test files misnamed for ExpiryBadge/DealSummary; mergeDraft keeps untrimmed conditions
- Tasks 17-18: minor (deferred): terms_changed closes counter dialog (draft re-prefills); flash on whole CompareColumns wrapper and before refetch lands; below_floor 422 without below_by_cents does nothing
- Tasks 17-18: minor (deferred): React Strict Mode dev — useId topic repeats across simulated remount while removeChannel is async; .on could throw in dev (same pre-existing exposure in batch doorbell); unmount-guard test is weak
- Tasks 19-20: minor (deferred): ?thread= stays in URL after drawer close; deals list→detail tested as separate renders; offers-page.test.tsx seen flaky once
- Tasks 19-20: minor (deferred, PRIORITY): frontend tests/unit/offers-page.test.tsx flaky (failed 2 of ~5 full runs) — final fix wave
- Tasks 19-20: minor (deferred): resolve dialog snapshot reads events at open (if detail not loaded, shows brief ask); task-19-20 report stale outside fix section
- Task 21: minor (deferred): m2.spec.ts likely broken by brief page pencil-edit UI (pre-existing drift); frontend/README "Coming in M2" stale line; m3 spec relies on realtime with 45s timeouts, no reload fallback
- Pre-existing: minor (deferred): test_try_call/test_try_email commit voice_try events to the shared DB and hit the 10/day quota after repeated suite runs — tests should use fresh users or clean up

## Parked at the final review

- Email on an `accepted` thread adds a terms event, so the brand's award gets a 409 and a re-preview with identical terms (fails safe).
- HTML-only replies: `html_to_text` drops `<blockquote>`, so inline answers in HTML-only mail are still lost; `raw_text` lacks the quoted history then.
- Unquoted footers after quoted history are kept as inline answers and reach Gemini.
- An inline line starting with "On " followed by a quoted "... wrote:" line can be read as an attribution.
- Call-sourced prices are not capped at MAX_PRICE_CENTS.
- `transcripts.raw_text` is unbounded and returned in every transcript list.
- Inbound: a brand counter that leaves the status at `awaiting_reply` mid-read is not caught by the lock re-check.
- Non-retryable inbound fetch codes beyond 400/422 (405, 410, 413) are dropped as ignored.
- Allow-list creator-visible event payloads; add FK indexes on outbox_emails/deals before data grows.

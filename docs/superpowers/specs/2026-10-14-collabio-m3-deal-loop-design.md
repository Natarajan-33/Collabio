# Collabio M3 — The Deal Loop (Design Spec)

| | |
|---|---|
| **Date** | 2026-10-14 |
| **Status** | Approved in brainstorming (§1–§3); awaiting written-spec review |
| **Parent spec** | `docs/superpowers/specs/2026-10-09-collabio-design.md` (v1). This spec **supersedes** the parent's M3/M4 rows and its demo framing wherever they disagree. |
| **Builds on** | `docs/superpowers/plans/2026-10-10-collabio-m2-launch.md` (Rulings 4, 6, 11, 16 in particular) |
| **Path** | Architectural — this spec, then one implementation plan |

---

## 1. Intent

### 1.1 Reframe: a production product, not a demo
Collabio ships to a real, paid production environment. Design for real brands and real creators using it unattended. Demo choreography (presenter, helper, stage fallbacks) no longer drives scope.

- **Brands** (small/mid DTC companies, their marketers) want sponsored content without days of outreach and haggling.
- **Creators** publish packages and want inbound offers they can compare and answer fast, without exposing their floor price.
- **Money model (stated by the user):** the brand pre-funds a campaign budget; the platform holds it; creators are paid from it as each deliverable is approved, so creators never chase payments. *Brand pays, platform facilitates, creators get paid predictably.* Money movement is M4; M3 builds the deal records it attaches to.

### 1.2 Roadmap (re-cut, agreed)
| # | Milestone | Contents |
|---|---|---|
| M1 | Foundation + supply | Done |
| M2 | Brief → parallel launch | Done |
| **M3** | **Deal loop** (this spec) | Creator offers inbox + offer desk; counters both ways, unlimited rounds; email-reply parsing; accept / decline / withdraw; offer expiry; award → **Deal** with **deliverable milestones**; notifications; contact reveal at booking; hide seeded creators in production |
| M4 | Money | Campaign funding held by the platform (Stripe Connect separate charges & transfers vs a licensed escrow provider — decided in M4's brainstorm); creator payout onboarding; deliverable submission → brand approval (auto-approve after N days) → milestone payout; platform fee; refund of unused budget; disputes freeze a milestone |
| M5 | Production hardening + growth | Deployment, rate/abuse limits, terms & privacy pages, analytics (both roles), email→call follow-ups, landing page, admin (disputes, review queue), notification digests |

### 1.3 Decisions made in brainstorming
1. **Multiple hires per campaign, up to a target.** The brief gains `hires_target` (default 1). Brands award one thread at a time; reaching the target prompts *decline the rest*; awarding past the target needs an explicit confirmation.
2. **Registered creators only.** Every offer recipient has an account, so the offer desk always works; email replies are a convenience channel. Seeded creators (`creators.profile_id is null`) are development fixtures, visible only when `DEMO_MODE` is on.
3. **Milestones: one per deliverable, editable at award.** Auto-split the agreed price evenly across the agreed videos (remainder cents on the last milestone), each due by the agreed go-live date. The brand may edit amounts and dates before confirming, within limits (§4.4) that make creator re-confirmation unnecessary.
4. **Accept ≠ award.** A creator accepting binds the creator to the brand's latest terms; the deal is booked only by the brand's **Award** click (keeps hire-target and spend under the brand's control).
5. **Dropped from scope:** "Take call in browser / Join call", helper personas, demo reset and preflight as milestone goals.

### 1.4 Success criteria
1. A brand and a creator close a deal end-to-end with no operator involvement: launch → (any number of counters in-app or by email, either side) → accept or counter → award → both see **Booked** with milestones and each other's contact email.
2. A creator who never opens the app can negotiate entirely by replying to emails; every reply lands on the right thread or is flagged for the brand, never silently dropped or guessed.
3. Double clicks, stale tabs, duplicate webhooks and process restarts never produce a second deal, a second notification, or an action on terms the user did not see.
4. Neither side ever sees the other's private limit (brand ceiling, creator floor); contact details cross sides only through a booked deal.
5. Every state change the counterpart needs to know about produces exactly one notification email.

### 1.5 Out of scope for M3
Money movement of any kind (M4); deliverable submission/approval (M4); disputes (M4/M5); brand teams / multiple users per brand; notification preferences and digests; in-app chat beyond the optional note on a counter; follow-up calls (M5); analytics (M5); admin console (M5); non-member creators / claim flow.

---

## 2. Thread lifecycle

### 2.1 Statuses
No new status strings. M3 starts using `awarded`, `closed_lost` and `no_response`, already permitted by the `threads.status` check constraint. A brand withdrawing an offer is `closed_lost` with `payload.reason = "withdrawn"`; declining the rest after an award is `closed_lost` with `reason = "not_selected"`; declining a creator's counter is `closed_lost` with `reason = "declined_by_brand"`.

### 2.2 Who holds the ball
| Status | Waiting on | Creator may | Brand may |
|---|---|---|---|
| `awaiting_reply` | creator | counter, accept, decline | withdraw |
| `countered` | brand | revise counter, decline | counter, award, decline |
| `accepted` | brand | decline (changed their mind before award) | award, decline |
| `needs_review` | brand | — | resolve, counter, decline |
| `no_response` | — (lapsed) | counter, accept, decline (late reply reopens) | counter (re-engage), withdraw |
| `awarded` | — (booked) | view deal | view deal |
| `declined`, `closed_lost` | — (closed) | — | — |
| `queued`, `drafting`, `calling`, `in_call`, `failed` | system | — | withdraw (not while `drafting`/`calling`/`in_call`); retry (`failed`, M2) |

### 2.3 Transitions added in M3 (`core/thread_state.py`)
```
awaiting_reply ─► countered | accepted | declined | needs_review | no_response | closed_lost | failed
countered      ─► countered (creator revises) | awaiting_reply (brand counter) | awarded | declined | closed_lost | needs_review
accepted       ─► awarded | declined | closed_lost
needs_review   ─► countered | accepted | declined | awaiting_reply | closed_lost
no_response    ─► countered | accepted | declined | needs_review | awaiting_reply (brand re-engages) | closed_lost
queued         ─► closed_lost (withdraw before work starts)
failed         ─► closed_lost
```
`awarded`, `declined`, `closed_lost` are terminal. `countered → countered` is the only self-transition. The M2 rows stay as they are.

### 2.4 Event → status
| Event (actor) | From | To | `latest_terms_source` |
|---|---|---|---|
| `counter_submitted` (creator, in-app) | `awaiting_reply`, `countered`, `no_response` | `countered` | creator |
| `email_received` (creator) with stance counter / accept / decline | `awaiting_reply`, `countered`, `no_response` | `countered` / `accepted` / `declined` | creator |
| `email_received` with stance question / no_commitment / offer, or confidence < 0.6, or sender mismatch | same | `needs_review` (payload `reason`) | unchanged |
| `email_received` on `accepted` / `needs_review` | — | no change (event + transcript recorded; brand notified with `brand_needs_review`) | unchanged |
| `email_received` on `awarded` / `declined` / `closed_lost` | — | no change (event + transcript recorded; no notification) | unchanged |
| `accepted` (creator, in-app) | `awaiting_reply`, `no_response` | `accepted` | creator (terms = the brand terms accepted, `stance = accept`) |
| `declined` (creator) | `awaiting_reply`, `countered`, `accepted`, `no_response` | `declined` | unchanged |
| `brand_counter_sent` (brand) | `countered`, `needs_review`, `no_response` | `awaiting_reply` | brand |
| `needs_review` → resolved: event `counter_submitted` / `accepted` / `declined` with `actor = brand`, `payload.resolved_review = true` | `needs_review` | per chosen outcome | creator (terms are the creator's, confirmed by the brand) |
| `awarded` (brand) | `countered`, `accepted` | `awarded` | unchanged |
| `closed_lost` (brand or system) | per §2.3 | `closed_lost` | unchanged |
| `offer_expired` (system, expiry sweep — §2.5) | `awaiting_reply` | `no_response` | unchanged |

### 2.5 Expiry
- `threads.expires_at` is set to `now() + batches.offer_ttl_days` whenever brand-side terms go out: `email_sent` (outreach), a call ending with the thread in `awaiting_reply`, and `brand_counter_sent`. It is cleared (`null`) when the thread leaves `awaiting_reply`.
- The expiry sweep (every 60 s) moves `awaiting_reply` threads with `expires_at < now()` to `no_response` by recording an event of the **new event type `offer_expired`** (actor `system`). This is the one event type M3 adds (migration extends the `thread_events.type` check and the `EventType` literal).
- A late creator reply (in-app or email) reopens a `no_response` thread as in §2.4.

### 2.6 Staleness guard
Creator `accept`/`counter` and brand `counter`/`award` requests carry `based_on_event_id`: the id of the latest terms-bearing event the user was looking at (the view models expose it as `terms_event_id`). If a newer terms-bearing event exists on the thread, the request fails with **409 `terms_changed`** and nothing is written. Terms-bearing events: `email_sent` (the ask), `call_ended`, `counter_submitted`, `email_received`, `accepted`, `brand_counter_sent`.

---

## 3. Data model (one migration: `…_m3_deal_loop.sql`)

### 3.1 Changes to existing tables
| Table | Change |
|---|---|
| `briefs` | `hires_target integer not null default 1 check (hires_target between 1 and 10)` |
| `batches` | `offer_ttl_days integer not null default 7 check (offer_ttl_days between 1 and 30)`; `hires_target` copied from the brief at launch |
| `threads` | `expires_at timestamptz`; partial index on `expires_at` where `status = 'awaiting_reply'` |
| `thread_events` | `type` check gains `offer_expired` |

### 3.2 New tables
**`deals`** — one per awarded thread; immutable after insert (trigger rejects UPDATE of everything except `status`).

| Column | Notes |
|---|---|
| `id uuid pk` | |
| `thread_id uuid unique not null` | one deal per thread, enforced |
| `batch_id`, `brand_id`, `creator_id`, `package_id` | denormalized for RLS and listing |
| `videos int not null ≥ 1`, `format text not null`, `price_cents int not null ≥ 1`, `go_live_by date not null` | the agreed terms |
| `conditions text[]`, `addons text[]` | |
| `awarded_event_id bigint not null` | the `awarded` event |
| `status text not null default 'booked'` | check `in ('booked')` in M3; M4 extends |
| `created_at timestamptz` | |

**`deal_milestones`**

| Column | Notes |
|---|---|
| `id uuid pk`, `deal_id uuid not null` | |
| `seq int not null ≥ 1` | `unique (deal_id, seq)` |
| `title text not null` | default "Video 1", "Video 2", … |
| `amount_cents int not null ≥ 1` | |
| `due_date date not null` | |
| `status text not null default 'pending'` | check `in ('pending')` in M3; M4 adds `funded`, `submitted`, `approved`, `paid`, `disputed` |

A deferred constraint trigger checks at commit that `sum(amount_cents) = deals.price_cents` and `count(*) = deals.videos` for every touched deal.

**`outbox_emails`** — transactional outbox for notification email.

| Column | Notes |
|---|---|
| `id bigserial pk` | |
| `kind text not null` | see §5.2 |
| `thread_id uuid not null`, `event_id bigint not null` | `unique (kind, event_id)` |
| `to_role text not null` | `brand` \| `creator` |
| `payload jsonb not null default '{}'` | template inputs that are not derivable later (e.g. a brand's note) |
| `status text not null default 'pending'` | `pending` \| `sent` \| `failed` \| `skipped` |
| `attempts int not null default 0`, `next_attempt_at timestamptz not null default now()`, `last_error text`, `resend_id text`, `created_at`, `sent_at` | |

### 3.3 Row-level security
| Table | Read | Write |
|---|---|---|
| `deals`, `deal_milestones` | the deal's brand owner or creator owner | backend only |
| `outbox_emails` | nobody (RLS on, no policies) | backend only |

The backend keeps enforcing ownership explicitly in every endpoint (parent spec §6.3).

### 3.4 Private limits (parent spec §6.2, extended)
- The creator **floor** is read only by `offers` endpoints of the owning creator (counter preview/submit warning). It never reaches a brand response, event, email, transcript, structurer prompt or log line.
- The brand **ceiling** is read only by brand endpoints (`board` counter preview/submit, award, ranking) and the M2 agent tools. The counter-rejection message naming the ceiling is shown only to the brand.
- **Contact details:** a creator's `email` reaches the brand, and the brief's `contact_email` reaches the creator, **only** through a deal view (`GET /deals/{id}`), i.e. after award. Phone numbers are never revealed.

---

## 4. Domain core (pure, test-first)

### 4.1 `core/thread_state.py`
Add the §2.3 rows; `status_for_event` covers `offer_expired → no_response`; `status_for_stance(stance, confidence)` (generalizes M2's `status_after_call`, which now delegates to it): counter → `countered`, accept → `accepted`, decline → `declined`, everything else or confidence < 0.6 → `needs_review`. (M2 call completion keeps its existing mapping of `question`/`no_commitment`/`offer` to `awaiting_reply` for calls — the agent already answered on the call; for email they need a human, hence `needs_review`.)

### 4.2 `core/guardrails.py` additions
- `floor_shortfall(price_cents, videos, package_volume, floor_cents) -> int | None` — floor is per package volume; scale linearly to `videos` (rounded up, in the creator's favour). Returns the shortfall in cents (creator-only).
- `brand_counter_violation(price_cents, videos, brief_videos, ceiling_cents) -> str | None` — "Above your ceiling of $X for N videos" (brand-only), using the same scaling as `check_counter`.
- `award_over_ceiling(...) -> int | None` — overage in cents; award requires `confirm_over_ceiling = true` when not None.

### 4.3 `core/terms.py` (new)
- `agreed_terms(latest: NegotiationTerms, brief) -> AgreedTerms | AwardBlock` — fills `go_live_by` and `format` from the brief when the latest terms omit them; blocks award when `videos` or `price_cents` is missing ("Terms incomplete — counter or resolve first").
- `terms_changed(a, b) -> list[str]` — names of fields that differ (desk highlighting, 409 response body).

### 4.4 `core/milestones.py` (new)
- `split_even(price_cents, videos, due) -> list[MilestoneDraft]` — `amount = price // videos`, remainder added to the last; titles "Video 1…N"; all due `due`.
- `validate_milestones(agreed: AgreedTerms, drafts) -> list[str]` — errors: count ≠ `agreed.videos`; any amount < 100 cents; sum ≠ `agreed.price_cents`; any `due_date` earlier than `agreed.go_live_by` (§4.4.1); empty or > 80-char title.

#### 4.4.1 Milestone date rule (normative)
The creator agreed to have all videos live by `go_live_by`. The brand may stagger milestones **later** than that date (giving the creator more time is always acceptable) but never **earlier** (that would demand faster delivery than agreed). Rule: `due_date >= agreed.go_live_by` for every milestone, and titles are non-empty (≤ 80 chars). Amounts may be redistributed freely as long as each is ≥ $1 and they sum to the agreed price. These limits guarantee the creator gets at least the agreed money by no earlier than the agreed date, so no creator re-confirmation is needed.

### 4.5 `core/email_quotes.py` (new)
`strip_reply(text) -> str` removes: lines from the first `On … wrote:` (single or wrapped over two lines) onward; `>`-prefixed lines; Outlook `-----Original Message-----` and `From: … Sent: …` header blocks; Gmail mobile separators; signatures after `-- ` and common "Sent from my iPhone/Android" lines. Pure, fixture-tested (Gmail web, Gmail mobile, Outlook desktop, Apple Mail, plain).

### 4.6 `core/reply_token.py` additions
`parse_reply_address(addresses: list[str], domain: str) -> str | None` — first `t-{token}@{domain}` (case-insensitive) among `to`/`received_for`, token validated against the alphabet and length.

### 4.7 `core/svix.py` (new)
`verify_svix(secret, msg_id, timestamp, signature_header, body: bytes, now, tolerance_s=300) -> bool` — `whsec_` prefix stripped, base64-decoded key, HMAC-SHA256 over `f"{id}.{timestamp}.{body}"`, base64; any space-separated `v1,<sig>` matching via `hmac.compare_digest`; rejects timestamps outside tolerance. Tested against Svix's published test vector.

---

## 5. Backend modules and pipelines

### 5.1 Email reply ingestion — `modules/inbound/`
Resend facts this design relies on (verified 2026-10-14 against resend.com/docs): any local part at the receiving domain is delivered; the `email.received` webhook carries metadata only (`email_id`, `from`, `to`, `received_for`, `subject`, `message_id`, attachments metadata); the body is fetched with `GET /emails/receiving/{id}` (`text`, `html`, `headers`); webhooks are Svix-signed and retried (immediately, 5 s, 5 m, 30 m, 2 h, 5 h, 10 h, 10 h) and can be replayed.

Pipeline for `POST /webhooks/resend/inbound`:
1. Verify Svix signature (`RESEND_WEBHOOK_SECRET`); invalid → 401. Ignore event types other than `email.received` (200).
2. Token from `to`/`received_for` (§4.6). Unknown or missing token → log at info, **200** (stop retries), nothing stored.
3. Idempotency: if an `email_received` event with `external_id = email_id` exists → 200.
4. Fetch the body (`EmailPort.get_received(email_id)`); transient failure → **503** so Resend retries.
5. `strip_reply(text or html→text)`; store a `transcripts` row (`kind = email_in`, `external_id = email_id`, subject, stripped body).
6. Sender check: normalized `from` address must equal the creator's email (case-insensitive); otherwise → `needs_review` with `reason = "unknown_sender"` (structurer not called).
7. Structurer (`structure_reply`, §5.4) with the brief ask, the creator's package, and the latest terms; the result's `source = email`.
8. `apply_event(type = email_received, external_id = email_id, transcript_id, terms, target per §2.4)`; enqueue `brand_creator_replied` notification (or `brand_needs_review`).
9. Thread in a terminal status: record `email_received` without transition; no notification for `awarded/declined/closed_lost`.

Attachments are ignored in M3 (noted in the brand-side timeline as "N attachments not imported").

### 5.2 Notifications — `modules/notify/`
- **Outbox writes** happen inside the same transaction as the event (helper `enqueue(conn, kind, thread, event_id, to_role, payload)`), using `on conflict (kind, event_id) do nothing`.
- **Sender worker** claims `pending` rows with `next_attempt_at <= now()` (`for update skip locked`, batch 10), renders the Jinja template, sends via Resend with idempotency key `outbox:{id}`, marks `sent` with `resend_id`. Failures back off `30 s × 2^attempts`; after 5 attempts → `failed` with `last_error`. Reserved-domain recipients (M2 rule) → `skipped`.
- **Kinds and recipients** (brand recipient = the brief's `contact_email`; creator recipient = `creators.email`):

| Kind | To | Trigger |
|---|---|---|
| `creator_brand_countered` | creator | `brand_counter_sent` (includes the brand's optional note, reply-to = thread token address, subject `Re: <outreach subject>`) |
| `creator_awarded` | creator | `awarded` (links to the deal) |
| `creator_closed` | creator | `closed_lost` (withdrawn / not selected / declined by brand) — Gemini-personalized polite paragraph with a fixed template fallback |
| `brand_creator_countered` | brand | `counter_submitted` (creator in-app) or `email_received` → `countered` |
| `brand_creator_accepted` | brand | `accepted` or `email_received` → `accepted` |
| `brand_creator_declined` | brand | `declined` / `email_received` → `declined` (includes the creator's reason) |
| `brand_needs_review` | brand | thread → `needs_review` from an email |

No notification for expiry in M3 (board shows it; digests are M5). Every email carries the M2 AI-assistance footer only when Gemini wrote part of it, and the unsubscribe link only on creator-bound mail.

### 5.3 Creator offers — `modules/offers/`
- `GET /offers` → `OfferListItem[]`: thread id, brand name, product name, status, waiting_on (`creator` \| `brand` \| `none`), closest package summary, delta headline + chips, total value (latest terms price, else ask), `expires_at`, `updated_at`. Filters: `tab = needs_you | waiting | booked | closed`; sort `fit | revenue | timeline` (fit = M2 audience-fit score when available, else package match).
- `GET /offers/{thread_id}` → `OfferDesk`: brand + product summary, three columns (`my_package`, `their_ask`, `latest`) with `changed` field flags, `terms_event_id`, allowed actions, events, transcripts (`email_out`, `email_in`, `call` — call transcripts are already creator-readable per RLS), `deal_id` when booked, and the creator's **own** floor for the package (creator-only field).
- `POST /offers/{id}/counter/preview {terms}` → validated terms, delta vs package, `floor_warning`.
- `POST /offers/{id}/counter {terms, based_on_event_id, confirm_below_floor, note?}` → `counter_submitted` (`source = in_app`, stance `counter`), outbox `brand_creator_countered`. Below floor without `confirm_below_floor` → 422 `below_floor`.
- `POST /offers/{id}/accept {based_on_event_id}` → `accepted` with terms = the brand's latest terms with `stance = accept`.
- `POST /offers/{id}/decline {reason?}` → `declined`, outbox `brand_creator_declined`.
- Ownership: the thread's `creator_id` must be the caller's creator; else 404.

### 5.4 Structurer generalization — `modules/negotiation/structurer.py`
Add `structure_reply(gemini, *, ask, package_one_liner, latest_terms, body) -> StructuredReply | None` with an email-specific system prompt (same number rules: never invent numbers; `price_cents` total; confidence < 0.6 when ambiguous). The prompt receives no ceiling and no floor. `structure_call` is unchanged.

### 5.5 Brand actions — `modules/board/` (extended)
- `POST /threads/{id}/counter/preview {terms}` → delta + `ceiling_violation` (brand-only).
- `POST /threads/{id}/counter {terms, note?, based_on_event_id}` → reject above ceiling (422 `above_ceiling`); `brand_counter_sent` (actor `brand`, terms `source = in_app`, stance `offer`); `expires_at` reset; outbox `creator_brand_countered`. The note (≤ 1000 chars) is stored in the event payload and shown to both sides.
- `POST /threads/{id}/resolve {outcome: counter|accept|decline, terms?}` → only from `needs_review`; records the creator's position as confirmed by the brand (§2.4). A reply that holds no position (or asks a question) is answered with a brand counter carrying a note, which moves the thread to `awaiting_reply`.
- `POST /threads/{id}/decline {reason?}` → `closed_lost` (`withdrawn` from `awaiting_reply`/`no_response`/`queued`/`failed`, `declined_by_brand` otherwise); outbox `creator_closed`.
- `POST /batches/{id}/decline-rest/preview` → the open threads that would close; `POST /batches/{id}/decline-rest` → `closed_lost` (`not_selected`) for each, each isolated (one failure does not stop the others), outbox per thread.
- Board view model additions: `BatchKpis.hired`, `BriefSummary.hires_target`, `ThreadCard.terms_event_id`, `ThreadCard.deal_id`, `ThreadCard.expires_at`, `ThreadCard.allowed_actions`; KPI `replied` also counts `email_received`.

### 5.6 Deals — `modules/deals/`
- `POST /threads/{id}/award/preview` → agreed terms (§4.3), `split_even` milestones, `over_ceiling_cents`, `hired`/`hires_target`, `would_reach_target`.
- `POST /threads/{id}/award {milestones, based_on_event_id, confirm_over_ceiling, confirm_over_target}` → in **one transaction**: conditional transition to `awarded` + `awarded` event + `deals` insert + `deal_milestones` inserts + outbox `creator_awarded`. Concurrency: `unique (thread_id)` on deals and the conditional transition guarantee one deal per thread; the hire-target count is read with the batch row locked (`select … for update` on `batches`) so two simultaneous awards cannot both slip under the target unconfirmed.
- Validation errors → 422 with field-level messages (`validate_milestones`).
- `GET /deals` (brand: its deals; creator: theirs) and `GET /deals/{id}` → `DealView`: terms, milestones, counterpart name, **counterpart contact email**, thread link, created_at.

### 5.7 Voice — `modules/voice/`
- New screens: `offers` (intents `open_offer{brand_ref}`, `navigate`), `offer_desk` (`counter{terms}`, `accept`, `decline{reason?}`, `navigate`).
- Board adds `counter{creator_ref, terms}`, `award{creator_ref}`, `decline{creator_ref}`.
- Spoken terms come back as a `TermsDraft` (videos, price in cents, go_live_by, conditions, note) that **pre-fills** the TermsCard/dialog. No voice intent sends, accepts, declines or awards anything; each opens its confirmation UI.
- `NavigateRoute` gains `/creator/offers`, `/creator/deals`, `/brand/deals`.

### 5.8 Discovery in production
`match_creators` and the discovery repo exclude creators with `profile_id is null` unless `settings.demo_mode` is true. Launch rejects any creator with `profile_id is null` when not in demo mode (422 `creator_not_registered`).

### 5.9 Workers
Started in the existing lifespan runtime alongside the orchestrator and call watcher: `outbox_sender` (every 5 s) and `expiry_sweep` (every 60 s). Both honour `WORKERS_ENABLED`, are restart-safe (state in Postgres, `skip locked`), and isolate per-row failures.

---

## 6. API summary (`/api/v1`, Supabase JWT unless noted)

| Area | Endpoints |
|---|---|
| Offers (creator) | `GET /offers`, `GET /offers/{thread_id}`, `POST /offers/{thread_id}/counter/preview`, `POST /offers/{thread_id}/counter`, `POST /offers/{thread_id}/accept`, `POST /offers/{thread_id}/decline` |
| Board (brand) | `POST /threads/{id}/counter/preview`, `POST /threads/{id}/counter`, `POST /threads/{id}/resolve`, `POST /threads/{id}/decline`, `POST /threads/{id}/award/preview`, `POST /threads/{id}/award`, `POST /batches/{id}/decline-rest/preview`, `POST /batches/{id}/decline-rest` |
| Deals (both roles) | `GET /deals`, `GET /deals/{id}` |
| Webhooks (no JWT; Svix) | `POST /webhooks/resend/inbound` |

Error contract: 401 auth/signature; 403 wrong role; 404 not owner or missing (never leak existence); 409 `terms_changed` / `stale_status` with the latest `terms_event_id`; 422 validation (`below_floor`, `above_ceiling`, `terms_incomplete`, `milestones_invalid`, `over_target`, `over_ceiling`, `creator_not_registered`); 503 dependency down (only where retry makes sense, e.g. inbound fetch).

Backend env added: `RESEND_WEBHOOK_SECRET` (already named in the parent spec), `RESEND_INBOUND_DOMAIN` becomes required for creator-bound negotiation mail (without it, reply-to is omitted and email replies are unavailable; the in-app path still works).

---

## 7. Screens

### 7.1 Creator
- **Offers** (`/creator/offers`): nav item enabled with a badge = count of `waiting_on = creator`. Tabs *Needs you · Waiting on brand · Booked · Closed*; sort fit / revenue / timeline; rows show brand, product, closest package, delta chips, total value (`num`), status pill, "expires in 3d". Realtime via a new `useCreatorDoorbell(creatorId)` (postgres_changes INSERT on `thread_events` filtered by `creator_id`), refetching the list.
- **Offer desk** (`/creator/offers/[threadId]`): header (brand, product, status, expiry); **My package | Their ask | Latest** compare with changed rows highlighted; timeline (reusing `components/board/Timeline`) and transcripts; actions per `allowed_actions`: **Accept** (confirm dialog listing exact terms), **Decline** (optional reason, typed or spoken), **Counter** (TermsCard: steppers/inputs + voice pre-fill, live delta, floor warning; below-floor send needs a second confirmation). On 409 the desk refetches, flashes the changed fields and shows "Terms changed — review the latest". Booked → banner linking to the deal.
- **Deals** (`/creator/deals`, `/creator/deals/[id]`): list and detail — terms, a "Payment schedule" section listing milestones (status `pending`), and the brand's contact email.

### 7.2 Brand
- **Thread drawer**: replaces the "Coming in M3" buttons with live actions per `allowed_actions`: **Award**, **Counter**, **Decline / Withdraw**, **Resolve** (needs_review: source email or transcript beside an editable TermsCard and an outcome picker).
- **Counter dialog**: TermsCard + optional note; above-ceiling error inline (brand-only copy).
- **Award dialog**: agreed terms, `MilestoneEditor` (add/remove disabled — count is fixed to videos; edit title, amount, date; running total vs agreed price; live validation; Confirm disabled until valid), over-ceiling and over-target confirmations, and when this award reaches the target, a checked-by-default *Politely decline the remaining N* option with the list.
- **Board**: KPI strip adds *Hired x / n*; booked cards show a "Booked" pill and link to the deal; "Decline remaining" bulk action with preview; cards show expiry for `awaiting_reply`.
- **Deals** (`/brand/deals`, `/brand/deals/[id]`): list and detail with the creator's contact email; nav item added.

### 7.3 Shared components (`components/deal/`)
`TermsCard` (controlled; fields videos, price, go-live, conditions, note; voice pre-fill merge), `CompareColumns`, `MilestoneEditor`, `DealSummary`, `ExpiryBadge`. Visual rules from the parent spec §14 apply (tabular numerals via `num`, motion only on state change, reduced-motion honoured, voice accent reserved for voice).

---

## 8. Error handling & resilience
- **Exactly-once:** conditional transitions (`UPDATE … WHERE status = any(expected)`), `unique (type, external_id)` for inbound emails, `unique (thread_id)` for deals, `unique (kind, event_id)` for outbox rows, Resend idempotency keys for sends.
- **Isolation:** inbound processing, outbox sends, expiry and decline-rest are per-row; one failure never stops the others.
- **Visibility:** inbound problems become `needs_review` with a reason the brand can act on (unknown sender, unclear reply, creator asked a question, structurer unavailable); outbox `failed` rows keep `last_error`.
- **Gemini down:** inbound replies → `needs_review` ("couldn't read this reply automatically"); polite-decline paragraphs fall back to a fixed template; voice pre-fill falls back to typing. No user action is ever blocked on Gemini.
- **Resend down:** inbound fetch → 503 (Resend retries); outbox backs off and retries.

---

## 9. Security
- Svix verification on the inbound webhook with a 5-minute tolerance; raw body used for verification.
- Sender address must match the thread's creator; otherwise `needs_review`, never auto-applied.
- Ownership enforced in code for every endpoint plus RLS on all new tables.
- Floor/ceiling/contact rules of §3.4 covered by leak tests.
- Inbound email content is untrusted: stored as text, rendered escaped, passed to Gemini only inside a delimited block with instructions to treat it as data.

---

## 10. Testing
- **Pure core (test-first):** new transitions (table-driven, including every forbidden move), `status_for_stance`, `split_even`, `validate_milestones` (dates, sums, counts), `floor_warning`, `brand_counter_violation`, `award_over_ceiling`, `agreed_terms`, `terms_changed`, `strip_reply` fixtures, `parse_reply_address`, `verify_svix` (Svix test vector, tampered body, expired timestamp, multiple signatures).
- **Database (real Postgres):** migration; deal immutability trigger; milestone sum/count deferred trigger; RLS — creators read only their deals, brands only theirs, outbox unreadable, floors still brand-unreadable; concurrent award → exactly one deal; concurrent awards at the hire target → second needs confirmation.
- **API:** every endpoint's ownership (other brand/creator → 404, wrong role → 403); 409 on stale `based_on_event_id`; below-floor and above-ceiling paths; award with invalid milestones; decline-rest isolation; inbound webhook — valid, bad signature, duplicate delivery, unknown token, sender mismatch, Gemini down, terminal thread.
- **Workers:** outbox — sends once across restarts, backs off, marks failed after 5, skips reserved domains; expiry — moves only expired `awaiting_reply` threads, idempotent.
- **Leak tests:** ceiling and floor (raw cents and formatted dollars) absent from every creator-facing response / brand-facing response respectively, all events, transcripts, outbox payloads and rendered emails; contact emails absent from every response except `DealView`.
- **Structurer eval:** extend `backend/evals/` with ~10 email replies (counter, accept, decline, question, ambiguous, signature noise); run on demand against live Gemini.
- **Frontend:** Vitest for `TermsCard`, `MilestoneEditor`, desk action gating and 409 handling, offers list tabs/sort, creator doorbell; Playwright smoke for the full loop (launch → creator counters in-app → brand counters → creator accepts → brand awards with milestone edit → both see Booked) using the demo accounts and typed voice commands.

---

## 11. Carried-over follow-ups folded into M3
Only items in files M3 already touches: thread drawer action placeholders (M2 Task 21), `VoiceIntent.navigate` typed as `NavigateRoute` (M1 Task 9), whitespace-only transcripts short-circuit before Gemini (M1 Task 9), email adapter error typing for the new `get_received` call. Everything else stays on the follow-up list for M5.

---

## 12. Risks
| Risk | Mitigation |
|---|---|
| Structurer misreads an email reply | Confidence gate → `needs_review`; brand resolves with the source beside the parsed terms; eval set |
| Creator replies from a different address | Sender mismatch → `needs_review` (never auto-applied); brand can resolve |
| Notification storms (bulk decline-rest) | Per-thread outbox rows, worker batch size 10, Resend rate limits respected by backoff |
| Receiving domain misconfigured | In-app path is complete on its own; missing `RESEND_INBOUND_DOMAIN` omits reply-to rather than breaking sends |
| M4 needs a different deal shape | Deals/milestones are append-only with status columns designed to be extended by M4 |

# Collabio — Business Use Case & Product Specification

> **Purpose:** Standalone product brief for rebuilding Collabio from scratch. This document captures **business intent, user workflows, features, communications, and data concepts**. It intentionally omits implementation and code so a greenfield build can choose concrete stack details via MCPs and skills.
>
> **Product direction (current):** **Voice-first, click-second, type-last.** Marketers and creators interact primarily through **spoken briefs**, **guided voice intake**, and **UI clicks** (select, compare, approve)—not long forms or manual email composition.
>
> **Planned platform capabilities (integration intent, not implementation):** **ElevenLabs** for conversational voice (intake agents, outbound/inbound negotiation, speech-to-text for transcripts), **Gemini** for embeddings and semantic search (and optional text structuring), **Supabase** for auth, persistence, and real-time updates. Transactional **email** remains a delivery channel, often **generated from voice** rather than typed.

---

## 1. Executive summary

### 1.1 What Collabio is

Collabio is a **two-sided marketplace** connecting **product owners** (brands, sellers, marketers) with **creators** (influencers) for sponsored content deals.

| Side | Who they are | What they need |
|------|----------------|----------------|
| **Product owner** | Company or seller marketing a product | Find creators in their domain, compare **pre-published packages**, negotiate at scale, award contracts. |
| **Creator** | Influencer with an audience | Publish clear **offering packages**, receive inbound brand interest, compare multiple offers against what they promised, accept or counter efficiently. |

The platform’s differentiator is **voice-orchestrated negotiation**:

- Product owners **speak** what they want (e.g. “Can you do three videos for the same thousand dollars as your two-video package?”).
- A **briefing agent** collects **mandatory deal fields** by voice (and minimal clicks) until the outreach is meaningful.
- The system reaches creators via **email and/or phone**, each message **customized to that creator’s profile and packages**.
- Product owners run **many parallel conversations** (e.g. ten creators at once), then **review transcripts and structured outcomes** to pick a winner.
- Creators see **all inbound approaches** in one place, with **visual comparison** of brand asks vs their listed packages, and can **reply by voice** (email or call path) with agent assistance.

Legacy MVP proved semantic discovery, email, and single outbound AI calls. The **target product** is a **voice-native negotiation operating system** for both sides—not a typing-heavy CRM.

### 1.2 Problem statement

| Pain | Who feels it | Why it matters |
|------|----------------|----------------|
| Creators’ pricing is ambiguous (DMs, vague rate cards) | Product owners | Hard to compare apples-to-apples before contacting anyone. |
| Outreach is one-by-one and manual | Product owners | Selecting ten creators means ten separate emails/calls and mental load. |
| Negotiation fields are incomplete | Both | Agents and humans waste threads without product, budget, deliverables, timeline. |
| Creators drowning in inbound brand mail | Creators | Ten brands ask for different deliverables; hard to see which fit **their** published packages. |
| Typing-heavy tools | Both | Marketers and creators want speed; voice + clicks match how deals are actually discussed. |
| No single thread of truth | Both | Email, call, and counter-offers live in different places with no structured comparison. |

### 1.3 Value proposition

- **Package transparency:** Creators define **videos per week/contract**, **topic/niche**, **base price**, **freebies**, **add-ons**, and **extras**—visible before any conversation starts.
- **Domain discovery:** Product owners find creators in their vertical via **semantic search** (Gemini embeddings) plus filters; **preview packages** before outreach.
- **Voice brief → structured outreach:** Mandatory **deal variables** captured by a **product-owner intake agent** (ElevenLabs); only then does the system contact creators.
- **Dual channel negotiation:** Same intent can go as **voice-authored email** or **AI phone call** (when telephony and creator preference allow).
- **Parallel campaigns:** One product, many creators—**concurrent customized negotiations**, separate **conversation threads** and **findings** per creator.
- **Creator command center:** Inbound offers compared to **my packages**; voice-assisted accept/decline/counter; pick which brand to sign.

### 1.4 Target users and roles

| Role | Registration | Primary workspace | Must not see |
|------|--------------|-----------------|--------------|
| **Product owner** | “I am a brand / seller” | Discovery, bulk select, voice brief, parallel outreach, comparison dashboard, contract award | Other brands’ campaigns; creator PII beyond platform rules |
| **Creator** | “I am a creator” | Package editor, inbound inbox, offer comparison, voice reply, deal calendar | Other creators’ private rates (unless public on profile) |
| **Platform admin** (future) | Internal | Compliance, abuse, billing, integration health | — |

**Authentication:** Same identity provider for both roles; **role chosen at registration** (and switchable only via verified onboarding, not casual toggle). **Separate page trees and navigation** per role—one login surface, two products-in-one.

### 1.5 Success metrics (product-level)

- Time from “I have a product” to “ten creators contacted” (target: minutes, mostly voice + clicks).
- **Package fit score** accuracy (creator offers aligned with listed packages).
- **Parallel conversation completion rate** (threads that reach a clear outcome: accept, reject, counter, no response).
- **Product owner decision time** after parallel outreach (time to award contract).
- **Creator response time** with agent-assisted replies vs manual email.
- **Transcript + structured summary** available for 100% of voice calls and voice-derived emails.

### 1.6 UX principles (non-negotiable)

1. **No long forms as the default**—use voice intake, smart defaults from product profile, and clicks (chips, toggles, select lists).
2. **Show before you speak**—creator **package cards** and comparison UI are visible **before** starting outreach.
3. **One brief, many personalized executions**—product owner states intent once; system **forks** per creator using their package + profile.
4. **Human approves, agent executes**—optional policy: agent drafts/sends only after explicit click “Launch outreach” (batch).
5. **Every thread is inspectable**—live or post-hoc **transcript**, **structured fields**, and **delta vs creator package** (e.g. “asked 3 videos; listed 2 for $1,000”).

---

## 2. Domain model (business entities)

### 2.1 Creator profile

Public-facing identity: name, avatar, platforms, niche/domain tags, region, languages, audience stats (followers, engagement), bio for semantic search.

### 2.2 Creator package (core marketplace unit)

Creators **define one or more packages** before brands contact them. Each package is a **comparable SKU** for negotiation.

| Field group | Examples | Business rules |
|-------------|----------|----------------|
| **Scope** | Topic/niche (e.g. tech reviews, skincare), content type (short video, long video, story, live) | Must align with creator’s domain tags for search. |
| **Volume** | Videos per week **or** per contract (e.g. “2 videos per contract”) | Clear time basis: weekly retainer vs fixed contract. |
| **Base price** | $1,000 per contract, currency | Required for package to be “bookable.” |
| **Included** | What’s in base (length, revisions, cross-posting) | Shown on card before outreach. |
| **Freebies** | Bonus post, extended usage rights, product-only deal | Optional; visible in comparison UI. |
| **Add-ons** | Extra video, rush delivery, exclusivity | Named add-on + **incremental price**. |
| **Extras / rounds** | “Additional revision round +$X,” “Whitelisting +$Y” | Optional line items. |
| **Availability** | Slots per month, lead time | Drives realistic timelines in agent negotiation. |
| **Preferred channel** | Email first, phone OK, email only | Routes outreach mode per creator. |

**Negotiation anchor:** All brand asks are compared to **this package** (system shows **delta**: more videos, lower price, extra add-ons).

### 2.3 Product owner profile

Brand/seller identity: company name, product name(s), category/domain, default pitch points, budget guardrails, compliance links, contact for contracts.

Optional: **product catalog** (one owner, many SKUs) for campaigns tied to a specific product.

### 2.4 Product / campaign brief

What the owner wants to promote in a negotiation batch.

| Concept | Purpose |
|---------|---------|
| Product being marketed | Name, description, key claims (voice-captured, structured) |
| Target creator domain | e.g. fitness, B2B SaaS |
| Negotiation intent | e.g. “Match their 2-video package but ask for 3 videos at same price” |
| Guardrails | Max budget, latest start date, must-have deliverables |
| Selected creators | Multi-select from discovery (e.g. 10) |

### 2.5 Mandatory deal variables (intake schema)

Before any outbound email or call, the **product-owner intake agent** must fill a **fixed schema** (admin-configurable over time). Suggested **required fields**:

| Variable | Meaning |
|----------|---------|
| `brand_name` | Who is reaching out |
| `product_name` | What is being promoted |
| `product_summary` | One-line value prop (voice → text) |
| `target_deliverables` | What you want (e.g. 3 videos, 60s each) |
| `timeline` | When content must go live |
| `budget_ceiling` | Max you will pay |
| `negotiation_ask` | Plain-language ask (e.g. “3 videos for $1,000”) |
| `flexibility` | What you can trade (timeline vs price vs deliverables) |
| `contact_email` | For creator to reply |
| `approval_to_send` | Explicit confirmation flag (click) |

**Confidence rule:** Intake agent does not launch creator-facing outreach until **all required variables are set** and owner **confirms** (voice + “Launch” click). Owner can **edit variables** via voice (“change budget to twelve hundred”) or click-to-edit on a summary card.

**Per-creator overrides (optional):** System may auto-suggest tweaks per package (e.g. Creator A lists 2 videos @ $1k → default ask references that package).

### 2.6 Conversation thread

One **thread** = one product owner ↔ one creator, scoped to one brief/batch.

| Attribute | Purpose |
|-----------|---------|
| Mode history | Email sent, call placed, inbound reply |
| Transcript | Full text from ElevenLabs STT / email body / call |
| Structured state | Extracted counters: deliverables, price, status |
| Package delta | Side-by-side: **listed package** vs **brand ask** vs **latest counter** |
| Status | Draft, awaiting creator, negotiating, accepted, rejected, expired, no response |

### 2.7 Parallel outreach batch

| Attribute | Purpose |
|-----------|---------|
| Batch ID | Groups N threads from one “Launch” action |
| Shared brief | Same owner variables |
| Per-thread customization | Agent tailors opener to creator name, package, niche |
| Aggregate dashboard | Owner sees all N threads; filter by status, best price, best fit |

### 2.8 Creator inbound offer

When a brand reaches out, creator sees an **offer** object:

- Brand + product summary  
- Ask vs **which of my packages** it’s closest to  
- Proposed deliverables, price, timeline  
- Suggested actions: Accept, Decline, Counter (voice), Ask for call  

### 2.9 Contract award (decision)

Product owner selects **one (or more) winning creators** from batch results; system records **agreed terms** and notifies losers (policy). Creator side: **accept** moves offer to **booked deal**.

### 2.10 User & session

- Role: `product_owner` | `creator`  
- Tied to Supabase-style auth (email/OAuth)  
- Row-level security: owners see their batches; creators see their inbox and packages only  

---

## 3. How email and voice work together (negotiation design)

This section is the **brainstorm made concrete**—the product should implement all paths below.

### 3.1 Three outreach modalities

| Modality | When to use | User experience | Creator experience |
|----------|-------------|-----------------|---------------------|
| **A. Voice brief → email** | Creator prefers email; async OK; no phone on file | Owner speaks to intake agent → structured email generated → sent | Professional email referencing **their package** and your **specific ask** |
| **B. Voice brief → AI phone call** | Creator allows phone; urgent or relationship-heavy | Same intake → ElevenLabs agent calls with dynamic variables | Live conversation; transcript stored |
| **C. Hybrid thread** | Email opens, call follows | Email first; if no reply in X days, auto-suggest call (owner approves) | Same thread; one timeline |

**Default routing rule:** Respect **creator package preferred channel**; owner can override only if platform policy allows (e.g. “call only if creator opted in”).

### 3.2 Single intent, dual rendering

The **negotiation intent** (e.g. “3 videos for $1,000”) is stored once as structured + natural language. The system **renders**:

- **Email body** (readable, quotable, legally archivable)  
- **Voice agent script context** (same facts, conversational tone)  

Gemini (or equivalent) may **normalize** voice into structured fields; ElevenLabs agents consume those fields as **dynamic variables**.

### 3.3 Example negotiation (business flow)

**Creator package:** 2 videos / contract, topic: consumer tech, **$1,000**, no freebies, add-on: +1 video **+$400**.

**Product owner ask (voice):** “I like their tech package but need three videos for the same thousand—can they do it?”

**System behavior:**

1. Intake agent confirms: deliverables = 3 videos, budget ceiling = $1,000, flexibility = “could move timeline if needed.”  
2. Thread shows **delta**: +1 video vs package, −$400 vs add-on list price.  
3. **Email path:** Message cites their listed 2-for-$1,000 and politely proposes 3-for-$1,000 with rationale (product fit, timeline).  
4. **Call path:** Agent states the same ask, listens for counter (e.g. “3 for $1,200” or “3 for $1,000 if 6-week timeline”).  
5. **Outcome:** Structured counter stored; transcript attached; owner notified to accept/counter/abandon.

### 3.4 Creator-side symmetry

Creators receive offers in **inbox**. For each offer:

- **Comparison panel:** My package column vs brand ask column.  
- **Voice counter:** “I can do three videos but at twelve hundred” → agent structures counter-email or schedules return call.  
- **Batch decisions:** Ten brands approached me—**sort by fit, revenue, timeline**; accept one, decline others with templated voice replies.

### 3.5 Transcripts and visibility

| Viewer | What they see |
|--------|----------------|
| Product owner | Per-thread transcript (email chain + call transcript), live status during call where provider supports it |
| Creator | Same thread on their side; their agent’s outbound replies included |
| Platform | Stored for dispute resolution and quality (retention policy) |

**Requirement:** Any voice interaction that results in outreach must produce **searchable transcript** and **structured summary** (status, price, deliverables, open questions).

### 3.6 What else to integrate (beyond email + voice)

| Capability | Why |
|------------|-----|
| **Supabase (auth + DB + realtime)** | Roles, packages, threads, live batch status updates on dashboards |
| **Gemini embeddings** | “Creators in my domain,” package-aware semantic search |
| **ElevenLabs** | Intake agents, outbound negotiation agents, STT/transcripts, optional creator reply agent |
| **Transactional email** | Inbound/outbound email threading (SendGrid/Resend/etc.)—**not replaced by voice**, fed by voice |
| **Telephony (e.g. Twilio)** | When direct call modality is on |
| **Notifications** | Push/email/in-app when thread updates (creator replied, call completed) |
| **Payments / escrow** (Phase 3) | Optional: pay on accept |
| **Calendar** (Phase 2) | Content deadlines after deal |
| **E-sign / contract PDF** (Phase 3) | Formalize awarded deal |
| **Webhook from ElevenLabs** | Call ended → summary job, thread update |

---

## 4. End-to-end user journeys

### 4.1 Registration and role routing

1. User lands on marketing site → **Register** or **Sign in**.  
2. **First-time:** Choose **I sell products** vs **I create content** (click).  
3. Complete minimal profile (voice optional for bio; clicks for role-specific essentials).  
4. Route to **Product Owner app** or **Creator app** (separate shells).  

### 4.2 Creator journey — publish packages

1. Open **My packages** → create package (guided voice: “How many videos per contract?” or click stepper).  
2. Set topic, price, freebies, add-ons, extras, preferred contact channel.  
3. Publish → profile discoverable by semantic search.  

### 4.3 Product owner journey — discover without typing

1. Open **Discovery** → optional **voice search** (“Find tech creators who do short videos under two thousand dollars”) **or** click domain filters.  
2. Browse **creator cards** with **package summaries** visible **before** contact.  
3. Multi-select creators (checkboxes) → **Review selection** screen shows all packages side-by-side.  

### 4.4 Product owner journey — voice intake and parallel launch

1. Click **Start negotiation** (batch).  
2. **Intake agent (ElevenLabs)** converses: fills mandatory deal variables; shows **summary card** on screen in real time.  
3. Owner corrects by voice or click until complete.  
4. Choose modalities per creator (respect defaults): **Email**, **Call**, or **Mixed**.  
5. Click **Launch to N creators** → N **threads** open; N parallel agent jobs.  
6. **Batch dashboard:** cards per creator—status, transcript snippet, package delta, recommended “best value.”  
7. Owner drills into any thread → full transcript + structured fields.  
8. **Award contract** to chosen creator(s); others auto-declined or left open per policy.  

### 4.5 Creator journey — manage inbound flood

1. **Inbox** lists new offers (from parallel brand outreach).  
2. Open offer → **comparison UI** (my package vs their ask).  
3. **Voice reply:** accept, decline, or counter → agent sends email or triggers call-back flow.  
4. **Decision board:** compare ten brands; pick which deal to take; visualize revenue and deliverables.  

### 4.6 Single-creator path (still supported)

From one card: same intake (abbreviated if brief already exists) → one email and/or one call—subset of batch flow.

---

## 5. Feature catalog

### 5.1 Role-based apps

| Feature | Product owner | Creator |
|---------|---------------|---------|
| Discovery / search | ✓ | — (own profile preview only) |
| Package CRUD | — | ✓ |
| Voice intake agent | ✓ | ✓ (for counters) |
| Bulk select + batch launch | ✓ | — |
| Parallel thread dashboard | ✓ | — |
| Inbound offer inbox | — | ✓ |
| Offer comparison vs packages | — | ✓ |
| Transcript viewer | ✓ | ✓ |
| Contract award / accept | ✓ | ✓ |

### 5.2 Voice intake agent (product owner)

- Conversational collection of **mandatory deal variables**.  
- Screen shows **filled vs missing** fields; blocks launch until complete.  
- Supports **change requests** by voice.  
- Ends with explicit **confirmation click**.  

### 5.3 Voice-to-email pipeline

- Transcript + structured fields → **personalized HTML/text email** per creator.  
- References creator’s **package name and terms**.  
- Threading: replies attach to same **conversation thread**.  

### 5.4 Voice negotiation agent (outbound call)

- ElevenLabs agent with per-thread **dynamic variables** (owner fields + creator package snapshot).  
- Telephony when enabled; transcript on completion.  
- Summary extraction into thread structured state.  

### 5.5 Parallel outreach orchestration

- Queue N outreach jobs from one batch.  
- **Per-creator customization** (not blast identical text).  
- Concurrency limits and spend caps per owner (business rule).  
- Realtime batch progress (Supabase realtime).  

### 5.6 Semantic discovery (Gemini embeddings)

- Embed creator profile + **package text** for domain search.  
- Hybrid: filters (price band, videos/week, region) + semantic query.  
- Voice query → text → search.  

### 5.7 Comparison and decision UX

- **Package delta** visualization (columns).  
- Sort/filter threads by price, fit, responsiveness.  
- **Creator decision board** for multiple inbound brands.  

### 5.8 Creator reply agent

- Voice → structured counter → email or call.  
- Must not commit below creator’s configured **floor** without explicit creator click (“Approve send”).  

### 5.9 Analytics (both roles)

- Owner: batch conversion, $ per deal, time to award.  
- Creator: inbound volume, accept rate, average deal size vs package list price.  

### 5.10 Settings (minimal typing)

- Integrations status (ElevenLabs, email).  
- Voice language, notification prefs.  
- Agent guardrails (max discount, forbidden claims).  

---

## 6. Communications matrix

| Channel | Direction | Trigger | Content source |
|---------|-----------|---------|----------------|
| In-app voice | User ↔ intake/reply agent | Start brief / counter | ElevenLabs |
| Email | Owner agent → creator | Batch launch, modality email | Rendered from structured brief + package |
| Email | Creator agent → owner | Counter/accept | Same |
| Phone | Owner agent ↔ creator | Call modality | ElevenLabs + telephony |
| In-app UI | User ↔ platform | Clicks, selects, approve | Supabase-backed state |
| Realtime updates | Platform → user | Thread status change | Supabase realtime / notifications |

---

## 7. Business rules & policies

### 7.1 Outreach gating

- No creator contact without **complete mandatory variables** and **launch approval**.  
- Creator **opt-in** for phone; email requires valid creator email on profile.  

### 7.2 Parallelism

- Default max concurrent outreach per batch (configurable tier).  
- Owner sees **per-thread** errors (bad number, bounce)—does not fail whole batch silently.  

### 7.3 Package integrity

- Creators are **truthful** on packages (terms of service); brands negotiate **against listed terms**.  
- System highlights when ask **violates** listed minimums (e.g. below base price) before send.  

### 7.4 Agent authority

- Agents **negotiate within** `budget_ceiling` and `flexibility` unless owner enables “agent may exceed with callback.”  
- Creators: agent cannot accept **below floor** without creator click.  

### 7.5 Compliance

- AI disclosure on calls and emails where required.  
- Recording consent for calls.  
- Email unsubscribe and commercial messaging rules.  
- PII isolation between roles (Supabase RLS).  

---

## 8. Non-functional requirements

| Area | Requirement |
|------|-------------|
| Voice UX | Sub-second feedback on intake; clear “listening / thinking / speaking” states |
| Parallel scale | 10+ simultaneous threads per owner (provider limits managed) |
| Search | Sub-second perceived for domain browse |
| Audit | Immutable thread log (transcript + structured events) |
| Security | Server-side API keys; no anonymous outreach |
| Cost control | Per-owner caps on ElevenLabs minutes and call spend |

---

## 9. Phased delivery recommendation

### Phase 1 — Two-sided foundation

- Role-based registration and **separate owner/creator apps**.  
- Creator **package CRUD** (click-first, optional voice).  
- Owner discovery with **package-visible cards** + Gemini semantic search.  
- Mandatory-variable **voice intake** + **voice-to-email** for **single** creator.  
- Threads with transcript storage.  

### Phase 2 — Parallel negotiation

- Multi-select + **batch launch** (N emails).  
- Per-thread dashboard and **package delta** UI.  
- Outbound **ElevenLabs phone** modality + transcripts.  
- Creator **inbox** + comparison + voice counter-email.  

### Phase 3 — Decision intelligence

- Creator **multi-brand decision board**.  
- Hybrid email→call follow-ups.  
- Award contract, notifications, calendar.  
- Payments / contracts (optional).  

---

## 10. Open product decisions

1. Max parallel outreach per tier (10 default?).  
2. Owner must approve each counter-send, or trust agent within guardrails?  
3. Public creator marketplace vs invite-only brands.  
4. Single ElevenLabs agent persona vs separate intake vs negotiation agents.  
5. Email provider choice and whether replies are parsed into threads automatically.  
6. Currency handling for global packages.  
7. Dispute flow when transcript and creator memory differ.  

---

## 11. Glossary

| Term | Meaning |
|------|---------|
| **Package** | Creator-defined offering SKU (scope, volume, price, add-ons). |
| **Intake agent** | Voice agent that fills owner mandatory fields before outreach. |
| **Thread** | One owner–creator negotiation timeline. |
| **Batch** | One launch to many creators sharing one brief. |
| **Package delta** | Diff between brand ask and creator’s listed package. |
| **Modality** | Email, call, or hybrid path for a thread. |
| **Structured summary** | Machine-readable outcome (price, deliverables, status). |

---

## 12. How to use this document

Greenfield build should:

1. Implement **two apps in one** (owner vs creator) with shared threads.  
2. Treat **creator packages** as the center of discovery and comparison.  
3. Wire **ElevenLabs** for intake, negotiation, and transcripts; **Gemini** for embeddings (and optional structuring); **Supabase** for data and realtime.  
4. Ship **batch parallel outreach** early in Phase 2—it is core to the marketer story.  
5. Keep typing to **edits and legal confirmations**, not primary input.  

*Evolved from Collabio MVP analysis and voice-first two-sided marketplace direction. Last updated: March 2026.*

# Architecture (PayPal hackathon build)

```mermaid
flowchart LR
    subgraph Browser
        UI["Next.js 16 app<br/>deals, money panel, proof dialog"]
        Studio["AG Studio dashboard<br/>/brand/money"]
    end

    subgraph Render
        Web["collabio-web<br/>Next.js server<br/>/api/demo-login, /api/ai/claude"]
        API["collabio-api<br/>FastAPI + in-process workers"]
        Cron["collabio-nightly<br/>cron 03:00 UTC"]
    end

    subgraph Core["Pure code, test-first"]
        Engine["settlement.py<br/>what is owed"]
        Policy["payout_policy.py<br/>auto-pay or approval"]
    end

    PayPal["PayPal sandbox<br/>Orders v2, Payouts,<br/>Refunds, Webhooks"]
    Anthropic["Anthropic<br/>Sonnet 5.5 (agent, vision)<br/>Haiku 5.5 (terms parser)"]
    Supabase["Supabase<br/>Postgres, Auth,<br/>Storage (proofs)"]

    UI --> Web
    Studio --> Web
    UI -->|REST + JWT| API
    Studio -->|GET /money/dashboard| API
    Web -->|dashboard agent turns| Anthropic
    Web -->|charge demo cap| API
    API --> Engine
    API --> Policy
    API -->|settlement agent, terms parser| Anthropic
    API -->|create/capture order, payouts, refunds| PayPal
    PayPal -->|webhooks| API
    API --> Supabase
    Web -->|session| Supabase
    Cron -->|POST /internal/nightly| API
```

## Pieces

| Piece | Where | What it does |
|---|---|---|
| Payout engine | `backend/app/core/settlement.py` | Pure, integer-cents maths: bonus for views, funding total, what is owed per video, the payable delta clamped to what is available, the refund. Table-driven tests. |
| Payout policy | `backend/app/core/payout_policy.py` | Pure decision: auto-pay only when checks pass, confidence is high, the read is within 5% of the claim, and the amount is within the brand's limit; otherwise approval. |
| PayPal adapter | `backend/app/adapters/paypal.py` | OAuth token cache with refresh-on-401, `PayPal-Request-Id` reused across retries, capture with `return=representation`, payouts, refunds, webhook verification. |
| Settlement agent | `backend/app/agents/settlement_agent.py` | Claude tool-use loop (≤ 8 steps): `get_deal_context`, `record_verification`, `pay_creator`. The model never passes an amount; `pay_creator` asks the engine and the policy. |
| Runner and workers | `backend/app/modules/money/` | One run per submission (unique), claimed with a lock; stale runs reclaimed; payout status synced by worker and webhook; nightly sweep. |
| Money ledger | `money_events` table | Append-only (a trigger blocks updates); every funding, payout and refund with its PayPal id. |
| Dashboard | `frontend/components/money-dashboard/` | AG Studio data sources over flat rows from `GET /money/dashboard`, a default report, and the "Ask Collabio" agent through `frontend/lib/ai/claude-adapter.ts` → `/api/ai/claude`. |
| Hackathon mode | `HACKATHON_MODE`, `NEXT_PUBLIC_HACKATHON_MODE` | Persona sign-in, calls off, daily caps, demo reset. Flags, not deletions. |

## Money invariants

- Amounts are integer cents in USD; rounding is floor.
- `paid or pending + refunded ≤ captured`, per deal.
- One capture per funding (double clicks and retries return the existing capture).
- One payout per (milestone, delta): the milestone row is locked during quote and pay, and
  `sender_batch_id` is unique.
- After close, payouts are rejected with `409 deal_closed`.

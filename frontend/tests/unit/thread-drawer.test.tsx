import { cleanup, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThreadDrawer } from "@/components/board/thread-drawer"
import { TooltipProvider } from "@/components/ui/tooltip"

const h = vi.hoisted(() => ({
  api: { GET: vi.fn() },
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))

function wrap(ui: ReactNode) {
  return render(<TooltipProvider>{ui}</TooltipProvider>)
}

const detail = {
  card: {
    id: "t1",
    creator: { id: "c1", name: "Priya", handle: "priya", initials: "PR" },
    channel_plan: "email" as const,
    status: "failed" as const,
    package: {
      id: "pkg",
      name: "Trio",
      content_type: "short_video" as const,
      niche: "beauty" as const,
      volume_count: 3,
      volume_basis: "per_contract" as const,
      base_price_cents: 150000,
      per_video_cents: 50000,
      one_liner: "3",
      lead_time_days: 14,
      preferred_channel: "email_first" as const,
      addons: [],
    },
    latest_terms: {
      videos: 3,
      price_cents: 120000,
      go_live_by: "2026-11-14",
      conditions: [],
      addons: [],
      stance: "counter" as const,
      source: "email" as const,
      confidence: 0.9,
      open_questions: [],
    },
    latest_terms_source: "creator" as const,
    delta: {
      package_id: "pkg",
      package_name: "Trio",
      listed_videos: 3,
      ask_videos: 3,
      latest_videos: 3,
      listed_price_cents: 150000,
      ask_price_cents: 100000,
      latest_price_cents: 120000,
      listed_per_video_cents: 50000,
      ask_per_video_cents: 33333,
      latest_per_video_cents: 40000,
      lead_time_days: 14,
      days_to_go_live: 20,
      headline: "Above ask",
      latest_headline: null,
      flags: ["below_base_price" as const],
    },
    last_event: null,
    email: null,
    live_offers: [],
    best_value: null,
    last_error: "No answer.",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  },
  events: [
    {
      id: 2,
      type: "email_sent" as const,
      actor: "system" as const,
      created_at: "2026-01-02T00:00:00Z",
      payload: {},
      terms: null,
    },
    {
      id: 1,
      type: "email_drafted" as const,
      actor: "system" as const,
      created_at: "2026-01-01T00:00:00Z",
      payload: {},
      terms: null,
    },
  ],
  transcripts: [
    {
      id: "tr-email",
      kind: "email_out",
      created_at: "2026-01-01T00:00:00Z",
      subject: "Hi",
      body_text: "Body",
      turns: [],
      summary: null,
    },
    {
      id: "tr-call",
      kind: "call",
      created_at: "2026-01-02T00:00:00Z",
      subject: null,
      body_text: null,
      turns: [{ role: "agent" as const, text: "Hello", t: 5 }],
      summary: "Settled",
    },
  ],
}

beforeEach(() => {
  h.api.GET.mockReset()
  h.api.GET.mockResolvedValue({ data: detail })
})

afterEach(cleanup)

describe("ThreadDrawer", () => {
  it("loads the thread when opened and refetches on refreshKey", async () => {
    const { rerender } = wrap(
      <ThreadDrawer
        threadId="t1"
        refreshKey={0}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    await waitFor(() => expect(h.api.GET).toHaveBeenCalledTimes(1))
    rerender(
      <TooltipProvider>
        <ThreadDrawer
          threadId="t1"
          refreshKey={1}
          onClose={vi.fn()}
          onRetry={vi.fn()}
        />
      </TooltipProvider>
    )
    await waitFor(() => expect(h.api.GET).toHaveBeenCalledTimes(2))
  })

  it("shows terms and the delta table", async () => {
    wrap(
      <ThreadDrawer
        threadId="t1"
        refreshKey={0}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(await screen.findByText("Compared with their package")).toBeTruthy()
    expect(screen.getByText("Videos")).toBeTruthy()
    expect(screen.getAllByText(/\$1,200/).length).toBeGreaterThan(0)
  })

  it("lists the timeline newest first with labels and times", async () => {
    wrap(
      <ThreadDrawer
        threadId="t1"
        refreshKey={0}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    await screen.findByText("Timeline")
    const items = screen.getAllByText(/Email/)
    expect(items.length).toBeGreaterThan(0)
  })

  it("expands a drafted email and a call summary", async () => {
    const user = userEvent.setup()
    wrap(
      <ThreadDrawer
        threadId="t1"
        refreshKey={0}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    await screen.findByText("Drafted email")
    await user.click(screen.getByText("Drafted email"))
    expect(screen.getByText("Body")).toBeTruthy()
    await user.click(screen.getByText("Call"))
    expect(screen.getByText("Settled")).toBeTruthy()
  })

  it("shows call turns as Agent and Creator with m:ss times", async () => {
    const user = userEvent.setup()
    wrap(
      <ThreadDrawer
        threadId="t1"
        refreshKey={0}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    await user.click(await screen.findByText("Call"))
    expect(screen.getByText(/Agent/)).toBeTruthy()
    expect(screen.getByText(/\[0:05\]/)).toBeTruthy()
  })

  it("offers Retry only for failed threads", async () => {
    wrap(
      <ThreadDrawer
        threadId="t1"
        refreshKey={0}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(await screen.findByRole("button", { name: "Retry" })).toBeTruthy()
  })

  it("shows M3 actions disabled", async () => {
    wrap(
      <ThreadDrawer
        threadId="t1"
        refreshKey={0}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    await screen.findByText("Counter by voice")
    expect(screen.getByRole("button", { name: "Award" }).hasAttribute("disabled")).toBe(
      true
    )
  })
})

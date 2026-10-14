import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ThreadCardView } from "@/components/board/thread-card"

vi.mock("@/components/ShinyText", () => ({
  default: ({ children }: { children: string }) => <span>{children}</span>,
}))
import type { components } from "@/lib/api/schema"

type ThreadCard = components["schemas"]["ThreadCard"]

afterEach(cleanup)

function thread(over: Partial<ThreadCard> = {}): ThreadCard {
  return {
    id: "t1",
    creator: {
      id: "c1",
      name: "Priya",
      handle: "priya",
      initials: "PR",
    },
    channel_plan: "email",
    status: "awaiting_reply",
    package: {
      id: "pkg",
      name: "Trio",
      content_type: "short_video",
      niche: "beauty",
      volume_count: 3,
      volume_basis: "per_contract",
      base_price_cents: 150000,
      per_video_cents: 50000,
      one_liner: "3 videos",
      lead_time_days: 14,
      preferred_channel: "email_first",
      addons: [],
    },
    latest_terms: {
      videos: 3,
      price_cents: 120000,
      go_live_by: "2026-11-14",
      conditions: [],
      addons: [],
      stance: "counter",
      source: "email",
      confidence: 0.9,
      open_questions: [],
    },
    latest_terms_source: "creator",
    terms_event_id: null,
    deal_id: null,
    expires_at: null,
    allowed_actions: [],
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
      headline: "$200 above listed",
      latest_headline: "$200 above ask",
      flags: [],
    },
    last_event: {
      id: 1,
      type: "email_sent",
      actor: "system",
      created_at: new Date(Date.now() - 120_000).toISOString(),
      payload: {},
      terms: null,
    },
    email: null,
    live_offers: [],
    best_value: null,
    last_error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...over,
  }
}

const now = new Date()

describe("ThreadCardView", () => {
  it("shows status, terms, delta headline and last event", () => {
    render(
      <ThreadCardView
        thread={thread()}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(screen.getByText("Sent")).toBeTruthy()
    expect(screen.getByText(/3 videos/)).toBeTruthy()
    expect(screen.getByText("$200 above ask")).toBeTruthy()
    expect(screen.getByText(/Email sent/)).toBeTruthy()
  })

  it("shows the drafted email, noting test addresses", () => {
    render(
      <ThreadCardView
        thread={thread({
          email: {
            subject: "Hello",
            body_text: "Hi Priya",
            delivered: false,
          },
        })}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(screen.getByText("Hi Priya")).toBeTruthy()
    expect(screen.getByText("Not delivered: test address")).toBeTruthy()
  })

  it("shows a calling indicator and live offers during a call", () => {
    render(
      <ThreadCardView
        thread={thread({
          status: "in_call",
          live_offers: [
            {
              videos: 3,
              price_cents: 130000,
              go_live_by: null,
              conditions: [],
              addons: [],
              stance: "offer",
              source: "call",
              confidence: 0.8,
              open_questions: [],
            },
            {
              videos: 3,
              price_cents: 125000,
              go_live_by: null,
              conditions: [],
              addons: [],
              stance: "counter",
              source: "call",
              confidence: 0.8,
              open_questions: [],
            },
          ],
        })}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(screen.getAllByText("In call").length).toBeGreaterThan(0)
    expect(screen.getByText(/\$1,300 · 3 videos — creator/)).toBeTruthy()
  })

  it("marks the best value with its reasons", () => {
    render(
      <ThreadCardView
        thread={thread({
          best_value: {
            thread_id: "t1",
            eligible: true,
            rank: 1,
            score: 1,
            per_video_cents: 30000,
            reasons: ["Lowest $/video"],
            ineligible_reason: null,
          },
        })}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(screen.getByText("Best value")).toBeTruthy()
    expect(screen.getByText("Lowest $/video")).toBeTruthy()
  })

  it("shows the failure reason and a Retry button", async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    render(
      <ThreadCardView
        thread={thread({
          status: "failed",
          last_error: "No answer.",
        })}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={onRetry}
      />
    )
    await user.click(screen.getByRole("button", { name: "Retry" }))
    expect(onRetry).toHaveBeenCalledWith("t1")
  })

  it("prices use tabular numerals", () => {
    render(
      <ThreadCardView
        thread={thread()}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    const price = screen.getByText(/3 videos · \$1,200/)
    expect(price.className).toMatch(/num/)
  })

  it("links a booked card to its deal", () => {
    render(
      <ThreadCardView
        thread={thread({ status: "awarded", deal_id: "deal-9" })}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(screen.getByText("Booked")).toBeTruthy()
    expect(
      screen.getByRole("link", { name: "View deal" }).getAttribute("href")
    ).toBe("/brand/deals/deal-9")
  })

  it("shows when an offer awaiting a reply expires", () => {
    const expires = new Date(now.getTime() + 3 * 24 * 3_600_000 + 60_000)
    render(
      <ThreadCardView
        thread={thread({
          status: "awaiting_reply",
          expires_at: expires.toISOString(),
        })}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(screen.getByText(/expires in/).textContent).toContain("3d")
  })

  it("shows no expiry once the thread has moved on", () => {
    render(
      <ThreadCardView
        thread={thread({
          status: "countered",
          expires_at: new Date(now.getTime() + 86_400_000).toISOString(),
        })}
        now={now}
        revealEmail={false}
        onOpen={vi.fn()}
        onRetry={vi.fn()}
      />
    )
    expect(screen.queryByText(/expires in/)).toBeNull()
  })
})

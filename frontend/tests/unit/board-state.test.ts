import { describe, expect, it } from "vitest"

import type { components } from "@/lib/api/schema"
import {
  briefAskLine,
  eventLabel,
  isLive,
  lastEventLine,
  sortThreads,
  termsLine,
} from "@/lib/board/state"

type ThreadCard = components["schemas"]["ThreadCard"]
type NegotiationTerms = components["schemas"]["NegotiationTerms"]

function card(
  id: string,
  over: Partial<ThreadCard> = {}
): ThreadCard {
  return {
    id,
    creator: {
      id: `c-${id}`,
      name: "Creator",
      handle: "handle",
      initials: "CR",
    },
    channel_plan: "email",
    status: "queued",
    package: {
      id: "pkg",
      name: "Pack",
      content_type: "short_video",
      niche: "consumer_tech",
      volume_count: 3,
      volume_basis: "per_contract",
      base_price_cents: 100000,
      per_video_cents: 33333,
      one_liner: "3 videos",
      lead_time_days: 14,
      preferred_channel: "email_first",
      addons: [],
    },
    latest_terms: null,
    latest_terms_source: null,
    delta: {
      package_id: "pkg",
      package_name: "Pack",
      listed_videos: 3,
      ask_videos: 3,
      latest_videos: null,
      listed_price_cents: 100000,
      ask_price_cents: 100000,
      latest_price_cents: null,
      listed_per_video_cents: 33333,
      ask_per_video_cents: 33333,
      latest_per_video_cents: null,
      lead_time_days: 14,
      days_to_go_live: 30,
      headline: "Same as listed",
      latest_headline: null,
      flags: [],
    },
    last_event: null,
    email: null,
    live_offers: [],
    best_value: null,
    last_error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  }
}

function terms(over: Partial<NegotiationTerms> = {}): NegotiationTerms {
  return {
    videos: 3,
    price_cents: 120000,
    go_live_by: "2026-11-14",
    conditions: [],
    addons: [],
    stance: "counter",
    source: "call",
    confidence: 0.9,
    open_questions: [],
    ...over,
  }
}

describe("board state", () => {
  it("sorts by best value with ineligible threads after", () => {
    const input = [
      card("a", {
        best_value: {
          thread_id: "a",
          eligible: false,
          rank: null,
          score: null,
          per_video_cents: null,
          reasons: [],
          ineligible_reason: "x",
        },
      }),
      card("b", {
        best_value: {
          thread_id: "b",
          eligible: true,
          rank: 2,
          score: 0.5,
          per_video_cents: 40000,
          reasons: [],
          ineligible_reason: null,
        },
      }),
      card("c", {
        best_value: {
          thread_id: "c",
          eligible: true,
          rank: 1,
          score: 0.9,
          per_video_cents: 30000,
          reasons: [],
          ineligible_reason: null,
        },
      }),
    ]
    const sorted = sortThreads(input, "best_value")
    expect(sorted.map((t) => t.id)).toEqual(["c", "b", "a"])
  })

  it("sorts by price per video with no-terms last", () => {
    const input = [
      card("none"),
      card("high", { latest_terms: terms({ price_cents: 150000, videos: 3 }) }),
      card("low", { latest_terms: terms({ price_cents: 90000, videos: 3 }) }),
    ]
    const sorted = sortThreads(input, "price")
    expect(sorted.map((t) => t.id)).toEqual(["low", "high", "none"])
  })

  it("sorts by status order and by recency", () => {
    const byStatus = sortThreads(
      [
        card("failed", { status: "failed" }),
        card("queued", { status: "queued" }),
        card("sent", { status: "awaiting_reply" }),
      ],
      "status"
    )
    expect(byStatus.map((t) => t.status)).toEqual([
      "queued",
      "awaiting_reply",
      "failed",
    ])

    const byRecent = sortThreads(
      [
        card("old", { updated_at: "2026-01-01T00:00:00Z" }),
        card("new", { updated_at: "2026-06-01T00:00:00Z" }),
      ],
      "recent"
    )
    expect(byRecent.map((t) => t.id)).toEqual(["new", "old"])
  })

  it("does not mutate its input", () => {
    const input = [card("a"), card("b")]
    const copy = [...input]
    sortThreads(input, "recent")
    expect(input).toEqual(copy)
  })

  it("formats terms and the last event", () => {
    expect(termsLine(terms())).toBe("3 videos · $1,200 · live by Nov 14")
    expect(termsLine(null)).toBe("No terms yet")
    const now = new Date("2026-01-01T12:02:00Z")
    expect(
      lastEventLine(
        {
          id: 1,
          type: "email_sent",
          actor: "system",
          created_at: "2026-01-01T12:00:00Z",
          payload: {},
          terms: null,
        },
        now
      )
    ).toBe("Email sent · 2 min ago")
    expect(
      lastEventLine(
        {
          id: 2,
          type: "call_offer_logged",
          actor: "system",
          created_at: "2026-01-01T12:01:59Z",
          payload: {},
          terms: null,
        },
        new Date("2026-01-01T12:02:00Z")
      )
    ).toBe("Offer logged during call · just now")
  })

  it("is live while any thread is queued, drafting, calling or in a call", () => {
    expect(isLive([card("a", { status: "accepted" })])).toBe(false)
    expect(isLive([card("a", { status: "drafting" })])).toBe(true)
    expect(isLive([card("a", { status: "in_call" })])).toBe(true)
  })

  it("labels unknown events with a capitalised phrase", () => {
    expect(eventLabel("email_bounced")).toBe("Email bounced")
  })

  it("builds the brief ask line", () => {
    expect(
      briefAskLine({
        brief_id: "b",
        product_name: "Lamp",
        deliverables_count: 3,
        deliverables_format: "short_video",
        ask_price_cents: 100000,
        budget_ceiling_cents: 120000,
        go_live_by: "2026-11-14",
        follow_up_policy: "off",
      })
    ).toBe("3 short videos · $1,000 · live by Nov 14")
  })
})

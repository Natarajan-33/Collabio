import { describe, expect, it } from "vitest"

import {
  AGENT_FIELDS,
  agentFieldToPatch,
  contextualUpdate,
  matchCreator,
  parseDollarsToCents,
} from "@/lib/brief/agent-tools"
import type { components } from "@/lib/api/schema"

type DealBrief = components["schemas"]["DealBrief"]

const DIGITS = "Give the amount in digits, for example 1200."

describe("parseDollarsToCents", () => {
  it.each([
    ["1200", 120000],
    ["1,200", 120000],
    ["$1,200", 120000],
    ["1200.50", 120050],
    [" 1200 ", 120000],
    ["$ 1200", 120000],
    ["999.5", 99950],
  ])("parses %s", (input, cents) => {
    expect(parseDollarsToCents(input)).toBe(cents)
  })

  it.each([
    "twelve hundred",
    "1.2k",
    "-5",
    "0",
    "",
    "$0.00",
    "12 dollars",
    "1,20",
    "1200.505",
    "1e3",
  ])("rejects %s", (input) => {
    expect(parseDollarsToCents(input)).toBeNull()
  })
})

describe("agentFieldToPatch", () => {
  it("lists the ten fields the agent may set", () => {
    expect(AGENT_FIELDS).toEqual([
      "deliverables_count",
      "deliverables_format",
      "deliverable_length_s",
      "go_live_by",
      "ask_price_usd",
      "budget_ceiling_usd",
      "negotiation_ask",
      "flexibility",
      "product_summary",
      "contact_email",
    ])
  })

  it("maps ask_price_usd to ask_price_cents", () => {
    expect(agentFieldToPatch("ask_price_usd", "$1,000")).toEqual({
      patch: { ask_price_cents: 100000 },
    })
  })

  it("maps budget_ceiling_usd to budget_ceiling_cents", () => {
    expect(agentFieldToPatch("budget_ceiling_usd", "2500.75")).toEqual({
      patch: { budget_ceiling_cents: 250075 },
    })
  })

  it("asks for digits when money is in words", () => {
    expect(agentFieldToPatch("ask_price_usd", "twelve hundred")).toEqual({
      error: DIGITS,
    })
    expect(agentFieldToPatch("budget_ceiling_usd", "-5")).toEqual({
      error: DIGITS,
    })
    expect(agentFieldToPatch("budget_ceiling_usd", "0")).toEqual({
      error: DIGITS,
    })
  })

  it("accepts an ISO date and rejects other shapes", () => {
    expect(agentFieldToPatch("go_live_by", "2026-11-14")).toEqual({
      patch: { go_live_by: "2026-11-14" },
    })
    expect(agentFieldToPatch("go_live_by", " 2026-11-14 ")).toEqual({
      patch: { go_live_by: "2026-11-14" },
    })
    for (const bad of [
      "next friday",
      "11/14/2026",
      "2026-13-40",
      "2026-02-30",
    ]) {
      expect(agentFieldToPatch("go_live_by", bad)).toEqual({
        error: "Give the date as YYYY-MM-DD.",
      })
    }
  })

  it("validates count and format", () => {
    expect(agentFieldToPatch("deliverables_count", "3")).toEqual({
      patch: { deliverables_count: 3 },
    })
    for (const bad of ["0", "three", "2.5", "-1", ""]) {
      expect(agentFieldToPatch("deliverables_count", bad)).toEqual({
        error: "Give the number of deliverables as a whole number.",
      })
    }
    expect(agentFieldToPatch("deliverables_format", " Short_Video ")).toEqual({
      patch: { deliverables_format: "short_video" },
    })
    expect(agentFieldToPatch("deliverables_format", "reel")).toEqual({
      error: "Format must be one of short_video, long_video, story, live.",
    })
  })

  it("validates the video length in seconds", () => {
    expect(agentFieldToPatch("deliverable_length_s", "45")).toEqual({
      patch: { deliverable_length_s: 45 },
    })
    expect(agentFieldToPatch("deliverable_length_s", "a minute")).toEqual({
      error: "Give the video length as a whole number of seconds.",
    })
  })

  it("splits flexibility and rejects unknown values", () => {
    expect(agentFieldToPatch("flexibility", "timeline, price")).toEqual({
      patch: { flexibility: ["timeline", "price"] },
    })
    expect(agentFieldToPatch("flexibility", "None")).toEqual({
      patch: { flexibility: ["none"] },
    })
    expect(agentFieldToPatch("flexibility", "speed")).toEqual({
      error: "Flexibility must be timeline, price, deliverables or none.",
    })
    expect(agentFieldToPatch("flexibility", "price, speed")).toEqual({
      error: "Flexibility must be timeline, price, deliverables or none.",
    })
  })

  it("passes text fields through trimmed and refuses empty ones", () => {
    expect(agentFieldToPatch("negotiation_ask", "  Three reels  ")).toEqual({
      patch: { negotiation_ask: "Three reels" },
    })
    expect(agentFieldToPatch("product_summary", "A lamp")).toEqual({
      patch: { product_summary: "A lamp" },
    })
    expect(agentFieldToPatch("negotiation_ask", "   ")).toEqual({
      error: "Give some text for that field.",
    })
  })

  it("checks the contact email", () => {
    expect(agentFieldToPatch("contact_email", " hi@lumen.test ")).toEqual({
      patch: { contact_email: "hi@lumen.test" },
    })
    expect(agentFieldToPatch("contact_email", "hi at lumen")).toEqual({
      error: "Give a full email address, like name@brand.com.",
    })
  })

  it("rejects unknown fields", () => {
    expect(agentFieldToPatch("colour", "red")).toEqual({
      error: `I can't set colour. Fields: ${AGENT_FIELDS.join(", ")}`,
    })
  })
})

describe("contextualUpdate", () => {
  const brief = {
    id: "b",
    status: "draft",
    creator_ids: [],
    approved_at: null,
    batch_id: null,
    missing: [],
    violations: [],
    ask_price_cents: 120000,
    go_live_by: "2026-11-14",
    deliverables_count: 3,
    deliverables_format: "short_video",
    flexibility: [],
    hires_target: 1,
  } satisfies DealBrief

  it("tells the agent what the brand changed on the card", () => {
    expect(contextualUpdate("ask_price_cents", brief)).toBe(
      "The brand set opening ask to $1,200 on the card."
    )
    expect(contextualUpdate("go_live_by", brief)).toBe(
      "The brand set go-live date to Nov 14, 2026 on the card."
    )
    expect(contextualUpdate("deliverables_count", brief)).toBe(
      "The brand set number of deliverables to 3 short videos on the card."
    )
  })
})

describe("matchCreator", () => {
  const creators = [
    { creator_id: "a", name: "Arjun Rao", handle: "arjun.builds" },
    { creator_id: "p", name: "Priya Shah", handle: "@priyashah" },
  ]

  it("matches by full name, first name and handle, in any case", () => {
    expect(matchCreator("Arjun Rao", creators)).toBe("a")
    expect(matchCreator("arjun", creators)).toBe("a")
    expect(matchCreator("PRIYA", creators)).toBe("p")
    expect(matchCreator("@arjun.builds", creators)).toBe("a")
    expect(matchCreator("priyashah", creators)).toBe("p")
    expect(matchCreator("  @PriyaShah ", creators)).toBe("p")
  })

  it("returns null when nobody matches", () => {
    expect(matchCreator("Zed", creators)).toBeNull()
    expect(matchCreator("", creators)).toBeNull()
    expect(matchCreator("@", creators)).toBeNull()
  })
})

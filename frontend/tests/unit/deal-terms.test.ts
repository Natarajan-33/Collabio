import { describe, expect, it } from "vitest"

import {
  draftToInput,
  mergeDraft,
  parseDollars,
  termsSummary,
  type TermsDraft,
} from "@/lib/deal/terms"

describe("parseDollars", () => {
  it.each([
    ["$1,200", 120000],
    ["1200", 120000],
    ["1,200.50", 120050],
    ["$ 99.5", 9950],
    ["0.99", 99],
    [" 45 ", 4500],
  ])("reads %j as %i cents", (text, cents) => {
    expect(parseDollars(text)).toBe(cents)
  })

  it.each([
    "",
    "   ",
    "abc",
    "12 dollars",
    "-5",
    "1,20",
    "1.234",
    ".50",
    "$",
    "1,200,",
    "1e3",
  ])("rejects %j", (text) => {
    expect(parseDollars(text)).toBeNull()
  })
})

describe("mergeDraft", () => {
  const current: TermsDraft = {
    videos: 3,
    price_cents: 100000,
    go_live_by: "2026-11-30",
    conditions: ["No exclusivity"],
    note: "First",
  }

  it("starts from the spoken terms when there is nothing yet", () => {
    const spoken: TermsDraft = {
      price_cents: 90000,
      conditions: ["Usage 30 days"],
    }
    expect(mergeDraft(null, spoken)).toEqual(spoken)
  })

  it("lets a spoken price win and keeps what was not spoken", () => {
    const merged = mergeDraft(current, { price_cents: 120000, conditions: [] })
    expect(merged.price_cents).toBe(120000)
    expect(merged.videos).toBe(3)
    expect(merged.go_live_by).toBe("2026-11-30")
    expect(merged.note).toBe("First")
  })

  it("appends spoken conditions without repeating one", () => {
    const merged = mergeDraft(current, {
      conditions: ["no exclusivity", "Usage 30 days", "Usage 30 days"],
    })
    expect(merged.conditions).toEqual(["No exclusivity", "Usage 30 days"])
  })

  it("does not blank a field the speaker left null", () => {
    const merged = mergeDraft(current, {
      videos: null,
      price_cents: null,
      conditions: [],
    })
    expect(merged.videos).toBe(3)
    expect(merged.price_cents).toBe(100000)
  })
})

describe("draftToInput", () => {
  it("is null while videos or price is missing", () => {
    expect(draftToInput({ price_cents: 100000, conditions: [] })).toBeNull()
    expect(draftToInput({ videos: 3, conditions: [] })).toBeNull()
    expect(
      draftToInput({ videos: 3, price_cents: null, conditions: [] })
    ).toBeNull()
  })

  it("carries the terms and leaves the note behind", () => {
    expect(
      draftToInput({
        videos: 3,
        price_cents: 120000,
        go_live_by: "2026-11-30",
        conditions: ["Usage 30 days"],
        note: "Thanks",
      })
    ).toEqual({
      videos: 3,
      price_cents: 120000,
      go_live_by: "2026-11-30",
      conditions: ["Usage 30 days"],
    })
  })

  it("sends no date when there is none", () => {
    expect(
      draftToInput({ videos: 1, price_cents: 5000, conditions: [] })?.go_live_by
    ).toBeNull()
  })
})

describe("termsSummary", () => {
  it("reads videos, price and go-live date", () => {
    expect(
      termsSummary({ videos: 3, price_cents: 120000, go_live_by: "2026-11-30" })
    ).toBe("3 videos · $1,200 · live by Nov 30, 2026")
  })

  it("says video for one and drops what is missing", () => {
    expect(
      termsSummary({ videos: 1, price_cents: 55050, go_live_by: null })
    ).toBe("1 video · $550.50")
    expect(
      termsSummary({ videos: null, price_cents: null, go_live_by: null })
    ).toBe("")
  })
})

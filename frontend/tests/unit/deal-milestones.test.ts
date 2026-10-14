import { describe, expect, it } from "vitest"

import type { components } from "@/lib/api/schema"
import { milestoneErrors } from "@/lib/deal/milestones"

type AgreedTerms = components["schemas"]["AgreedTerms"]
type MilestoneDraft = components["schemas"]["MilestoneDraft"]

// The same fixtures as backend/tests/core/test_milestones.py.
const AGREED: AgreedTerms = {
  videos: 3,
  format: "short_video",
  price_cents: 110000,
  go_live_by: "2026-11-30",
  conditions: [],
  addons: [],
}

type Row = [number, number, string]
const GOOD: Row[] = [
  [1, 50000, "2026-11-30"],
  [2, 30000, "2026-12-07"],
  [3, 30000, "2026-12-14"],
]

function ms(rows: Row[]): MilestoneDraft[] {
  return rows.map(([seq, amount, due]) => ({
    seq,
    title: `Video ${seq}`,
    amount_cents: amount,
    due_date: due,
  }))
}

describe("milestoneErrors", () => {
  it("passes a valid schedule", () => {
    expect(milestoneErrors(AGREED, ms(GOOD))).toEqual([])
  })

  it("reports a wrong count alone", () => {
    expect(milestoneErrors(AGREED, ms(GOOD.slice(0, 2)))).toEqual([
      "Expected 3 milestones, one per video",
    ])
  })

  it("reports a wrong sum", () => {
    const rows = ms([[1, 40000, "2026-11-30"], GOOD[1], GOOD[2]])
    expect(milestoneErrors(AGREED, rows)).toEqual([
      "Payments add up to $1,000, not the agreed $1,100",
    ])
  })

  it("rejects a date before go-live, naming the video by number", () => {
    const rows = ms([GOOD[0], [2, 30000, "2026-11-29"], GOOD[2]])
    rows[1].title = "Intro cut"
    expect(milestoneErrors(AGREED, rows)).toEqual([
      "Video 2 is due before the agreed go-live date Nov 30, 2026",
    ])
  })

  it("rejects a payment under $1", () => {
    const rows = ms([GOOD[0], [2, 99, "2026-12-07"], GOOD[2]])
    expect(milestoneErrors(AGREED, rows)).toContain(
      "Each payment must be at least $1"
    )
  })

  it("rejects numbers that do not run 1 to n", () => {
    const rows = ms([GOOD[0], GOOD[1], [4, 30000, "2026-12-14"]])
    expect(milestoneErrors(AGREED, rows)).toEqual([
      "Milestone numbers must run 1 to 3",
    ])
  })

  it("rejects a blank or long title", () => {
    const blank = ms(GOOD)
    blank[0].title = "   "
    expect(milestoneErrors(AGREED, blank)).toEqual([
      "Every milestone needs a title of at most 80 characters",
    ])
    const long = ms(GOOD)
    long[2].title = "x".repeat(81)
    expect(milestoneErrors(AGREED, long)).toEqual([
      "Every milestone needs a title of at most 80 characters",
    ])
  })

  it("keeps the backend check order", () => {
    const rows = ms([
      [1, 50, "2026-11-01"],
      [2, 30000, "2026-12-07"],
      [4, 30000, "2026-12-14"],
    ])
    rows[1].title = ""
    expect(milestoneErrors(AGREED, rows)).toEqual([
      "Milestone numbers must run 1 to 3",
      "Each payment must be at least $1",
      "Payments add up to $600.50, not the agreed $1,100",
      "Video 1 is due before the agreed go-live date Nov 30, 2026",
      "Every milestone needs a title of at most 80 characters",
    ])
  })
})

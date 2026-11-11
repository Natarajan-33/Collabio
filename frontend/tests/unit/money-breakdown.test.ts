import { describe, expect, it } from "vitest"

import { breakdownLines, payoutStatusLabel } from "@/lib/money/format"

describe("payout breakdown", () => {
  it("lists only the parts that apply", () => {
    expect(
      breakdownLines({
        base: 40000,
        cpm: 50000,
        tiers: 0,
        already_committed: 40000,
        delta: 50000,
      })
    ).toEqual([
      { label: "Agreed price for the video", cents: 40000 },
      { label: "CPM bonus", cents: 50000 },
      { label: "Already paid or pending", cents: -40000 },
      { label: "Owed now", cents: 50000 },
    ])
  })

  it("handles a missing breakdown", () => {
    expect(breakdownLines({})).toEqual([{ label: "Owed now", cents: 0 }])
  })

  it("labels payout statuses", () => {
    expect(payoutStatusLabel("awaiting_approval")).toBe(
      "Waiting for brand approval"
    )
    expect(payoutStatusLabel("sent")).toBe("Sent via PayPal · pending")
    expect(payoutStatusLabel("success")).toBe("Paid")
  })
})

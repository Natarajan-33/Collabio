import { describe, expect, it } from "vitest"

import { formatExample, formatViews, ledgerLabel } from "@/lib/money/format"

describe("money formatting", () => {
  it("abbreviates view counts", () => {
    expect(formatViews(1_000_000)).toBe("1M")
    expect(formatViews(1_240_000)).toBe("1.24M")
    expect(formatViews(500_000)).toBe("500K")
    expect(formatViews(812_400)).toBe("812.4K")
    expect(formatViews(950)).toBe("950")
  })

  it("formats a bonus example", () => {
    expect(formatExample({ views: 1_000_000, bonus_cents: 80000 })).toBe(
      "1M views → +$800"
    )
    expect(formatExample({ views: 100_000, bonus_cents: 0 })).toBe(
      "100K views → no bonus"
    )
  })

  it("labels ledger entries", () => {
    expect(ledgerLabel("funded")).toBe("Funded via PayPal Checkout")
    expect(ledgerLabel("payout_succeeded")).toBe("Payout received")
    expect(ledgerLabel("refunded")).toBe("Unspent budget refunded")
  })
})

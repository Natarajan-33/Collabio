import { describe, expect, it } from "vitest"

import { formatCents } from "@/lib/money"

describe("formatCents", () => {
  it("formats cents", () => {
    expect(formatCents(100000)).toBe("$1,000")
    expect(formatCents(99950)).toBe("$999.50")
  })

  it("drops the decimals only when there are no cents", () => {
    expect(formatCents(0)).toBe("$0")
    expect(formatCents(5)).toBe("$0.05")
    expect(formatCents(100)).toBe("$1")
    expect(formatCents(101)).toBe("$1.01")
  })

  it("groups thousands", () => {
    expect(formatCents(123456789)).toBe("$1,234,567.89")
    expect(formatCents(100000000)).toBe("$1,000,000")
  })

  it("puts the sign before the currency symbol", () => {
    expect(formatCents(-500)).toBe("-$5")
    expect(formatCents(-99950)).toBe("-$999.50")
  })
})

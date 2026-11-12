import { describe, expect, it } from "vitest"

import { OFFER_TABS } from "@/lib/deal/offers"
import { flowFor } from "@/lib/flow"

describe("flowFor", () => {
  it("lays out the brand's four steps and marks where you are", () => {
    const f = flowFor("brand", "/brand/batches/abc")
    expect(f.steps.map((s) => s.label)).toEqual(["Discover", "Outreach", "Booked", "Money"])
    expect(f.steps.find((s) => s.current)?.label).toBe("Outreach")
    expect(f.hint).toMatch(/book/i)
  })

  it("explains when a creator becomes a booked deal", () => {
    expect(flowFor("brand", "/brand/deals").hint).toMatch(/fund/i)
    expect(flowFor("brand", "/brand/discover/review").steps.find((s) => s.current)?.label).toBe(
      "Discover"
    )
  })

  it("gives the creator three steps", () => {
    const f = flowFor("creator", "/creator/offers")
    expect(f.steps.map((s) => s.label)).toEqual(["Packages", "Offers", "Booked"])
    expect(f.steps.find((s) => s.current)?.label).toBe("Offers")
  })

  it("has no current step off the main pages", () => {
    expect(flowFor("brand", "/onboarding").steps.some((s) => s.current)).toBe(false)
  })
})

describe("creator offer tabs", () => {
  it("no longer repeat booked deals (they live under Booked)", () => {
    expect(OFFER_TABS.map((t) => t.key)).not.toContain("booked")
  })
})

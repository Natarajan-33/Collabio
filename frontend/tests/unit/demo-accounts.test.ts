import { describe, expect, it } from "vitest"

import { demoAccounts, plusAddress } from "@/lib/auth/demo"

describe("plusAddress", () => {
  it("adds a tag to the mailbox, like the seed does", () => {
    expect(plusAddress("a.b@x.com", "arjun")).toBe("a.b+arjun@x.com")
  })
})

describe("demoAccounts", () => {
  it("lists the brand, the helper creator and the derived second creator", () => {
    expect(
      demoAccounts({ brand: "shop@demo.test", helper: "ana.helper@demo.test" })
    ).toEqual([
      { email: "shop@demo.test", who: "Brand · Lumen" },
      { email: "ana.helper@demo.test", who: "Creator · Priya" },
      { email: "ana.helper+arjun@demo.test", who: "Creator · Arjun" },
    ])
  })

  it("ignores surrounding whitespace, as the seed does", () => {
    expect(
      demoAccounts({ brand: "  shop@demo.test\n", helper: " h@demo.test " })
    ).toEqual([
      { email: "shop@demo.test", who: "Brand · Lumen" },
      { email: "h@demo.test", who: "Creator · Priya" },
      { email: "h+arjun@demo.test", who: "Creator · Arjun" },
    ])
  })

  it("lists only what is configured", () => {
    expect(
      demoAccounts({ brand: "shop@demo.test" }).map((a) => a.email)
    ).toEqual(["shop@demo.test"])
    expect(demoAccounts({ helper: "h@demo.test" }).map((a) => a.email)).toEqual(
      ["h@demo.test", "h+arjun@demo.test"]
    )
  })

  it("is empty, so the hint stays hidden, when nothing is set", () => {
    expect(demoAccounts({})).toEqual([])
    expect(demoAccounts({ brand: "", helper: "   " })).toEqual([])
  })

  it.each(["not-an-email", "@demo.test", "me@"])(
    "refuses %s rather than showing an account that cannot exist",
    (bad) => {
      expect(demoAccounts({ brand: bad, helper: bad })).toEqual([])
    }
  )
})

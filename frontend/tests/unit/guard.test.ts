// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest"

import { guardRoute } from "@/lib/auth/guard"

const { getMe } = vi.hoisted(() => ({ getMe: vi.fn() }))
vi.mock("@/lib/auth/me", () => ({ getMe }))

// Next's redirect() throws to unwind the render; model that so a missing early exit
// would show up as a returned value instead.
class Redirected extends Error {
  constructor(readonly to: string) {
    super(`redirect:${to}`)
  }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Redirected(to)
  },
}))

function me(role: "brand" | "creator" | null) {
  return {
    kind: "ok" as const,
    me: {
      user_id: "u1",
      email: "x@example.com",
      role,
      display_name: null,
      brand: null,
      creator: null,
    },
  }
}

describe("guardRoute", () => {
  beforeEach(() => getMe.mockReset())

  it("lets a user into the tree for their role", async () => {
    getMe.mockResolvedValue(me("brand"))

    expect(await guardRoute("/brand")).toEqual(me("brand"))
  })

  it("sends an anonymous visitor to sign-in", async () => {
    getMe.mockResolvedValue({ kind: "anonymous" })

    await expect(guardRoute("/brand")).rejects.toMatchObject({
      to: "/sign-in?next=%2Fbrand",
    })
  })

  it("sends a user without a role to onboarding", async () => {
    getMe.mockResolvedValue(me(null))

    await expect(guardRoute("/creator")).rejects.toMatchObject({
      to: "/onboarding",
    })
  })

  it("sends a creator out of the brand tree", async () => {
    getMe.mockResolvedValue(me("creator"))

    await expect(guardRoute("/brand")).rejects.toMatchObject({
      to: "/creator/packages",
    })
  })

  it("sends a brand out of the creator tree", async () => {
    getMe.mockResolvedValue(me("brand"))

    await expect(guardRoute("/creator")).rejects.toMatchObject({
      to: "/brand/discover",
    })
  })

  it("sends an onboarded user off onboarding", async () => {
    getMe.mockResolvedValue(me("creator"))

    await expect(guardRoute("/onboarding")).rejects.toMatchObject({
      to: "/creator/packages",
    })
  })

  it("passes an unavailable backend through for the caller to show", async () => {
    getMe.mockResolvedValue({ kind: "unavailable", reason: "unreachable" })

    expect(await guardRoute("/brand")).toEqual({
      kind: "unavailable",
      reason: "unreachable",
    })
  })
})

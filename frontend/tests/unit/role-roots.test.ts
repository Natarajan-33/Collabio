// @vitest-environment node
import { describe, expect, it, vi } from "vitest"

import BrandRoot from "@/app/brand/page"
import CreatorRoot from "@/app/creator/page"

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

describe("role roots", () => {
  it("/brand goes to Discover instead of a 404", () => {
    expect(() => BrandRoot()).toThrowError(
      expect.objectContaining({ to: "/brand/discover" })
    )
  })

  it("/creator goes to Packages instead of a 404", () => {
    expect(() => CreatorRoot()).toThrowError(
      expect.objectContaining({ to: "/creator/packages" })
    )
  })
})

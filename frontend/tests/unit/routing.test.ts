import { describe, expect, it } from "vitest"

import {
  isGuardedPath,
  resolveRoute,
  roleHome,
  safeNextPath,
} from "@/lib/auth/routing"

describe("roleHome", () => {
  it("sends each role to its first screen", () => {
    expect(roleHome("brand")).toBe("/brand/discover")
    expect(roleHome("creator")).toBe("/creator/packages")
  })
})

describe("resolveRoute", () => {
  it("anonymous → sign-in with next", () =>
    expect(resolveRoute(null, "/brand/discover")).toBe(
      "/sign-in?next=%2Fbrand%2Fdiscover"
    ))

  it("no role → onboarding", () =>
    expect(resolveRoute({ role: null }, "/brand/discover")).toBe("/onboarding"))

  it("brand on creator route", () =>
    expect(resolveRoute({ role: "brand" }, "/creator/packages")).toBe(
      "/brand/discover"
    ))

  it("creator on brand route", () =>
    expect(resolveRoute({ role: "creator" }, "/brand/discover")).toBe(
      "/creator/packages"
    ))

  it("allowed", () =>
    expect(
      resolveRoute({ role: "brand" }, "/brand/discover/review")
    ).toBeNull())

  it("onboarded user on onboarding", () =>
    expect(resolveRoute({ role: "creator" }, "/onboarding")).toBe(
      "/creator/packages"
    ))

  it("a user without a role may stay on onboarding", () =>
    expect(resolveRoute({ role: null }, "/onboarding")).toBeNull())

  it("anonymous on onboarding → sign-in with next", () =>
    expect(resolveRoute(null, "/onboarding")).toBe(
      "/sign-in?next=%2Fonboarding"
    ))

  it("keeps the query string in next", () =>
    expect(resolveRoute(null, "/brand/discover?q=tech&region=IN")).toBe(
      "/sign-in?next=%2Fbrand%2Fdiscover%3Fq%3Dtech%26region%3DIN"
    ))

  it("guards the role root itself, not just its children", () => {
    expect(resolveRoute({ role: "brand" }, "/creator")).toBe("/brand/discover")
    expect(resolveRoute({ role: "creator" }, "/brand")).toBe(
      "/creator/packages"
    )
  })

  it("does not mistake a lookalike prefix for a role tree", () => {
    expect(resolveRoute({ role: "creator" }, "/brandon")).toBeNull()
    expect(resolveRoute({ role: "brand" }, "/creators")).toBeNull()
  })

  it("matches the role tree on its path, ignoring the query", () => {
    expect(resolveRoute({ role: "brand" }, "/creator/packages?x=1")).toBe(
      "/brand/discover"
    )
  })
})

describe("isGuardedPath", () => {
  it.each(["/brand", "/brand/discover", "/creator/packages", "/onboarding"])(
    "guards %s",
    (path) => expect(isGuardedPath(path)).toBe(true)
  )

  it.each(["/", "/sign-in", "/sign-up", "/brandon", "/onboarding-tips"])(
    "leaves %s open",
    (path) => expect(isGuardedPath(path)).toBe(false)
  )
})

describe("safeNextPath", () => {
  it("keeps an in-app path", () => {
    expect(safeNextPath("/brand/discover?q=tech")).toBe(
      "/brand/discover?q=tech"
    )
  })

  it.each([
    ["missing", undefined],
    ["empty", ""],
    ["an absolute URL", "https://evil.example/brand"],
    ["a protocol-relative URL", "//evil.example"],
    ["a backslash trick", "/\\evil.example"],
    ["a relative path", "brand/discover"],
    ["an auth page", "/sign-in"],
    ["an auth page with a query", "/sign-up?next=%2F"],
  ])("falls back to the root for %s", (_label, value) => {
    expect(safeNextPath(value)).toBe("/")
  })

  it("takes the first value when the param is repeated", () => {
    expect(safeNextPath(["/creator/packages", "/brand/discover"])).toBe(
      "/creator/packages"
    )
  })
})

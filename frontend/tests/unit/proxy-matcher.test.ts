// @vitest-environment node
import { describe, expect, it } from "vitest"

import { config } from "@/proxy"

// Next compiles a matcher with path-to-regexp; for this pattern (one parenthesised
// regex group) an anchored RegExp over the same source behaves the same way.
const matcher = new RegExp(`^${config.matcher[0]}$`)

describe("proxy matcher", () => {
  it("escapes the dot before the file extension", () => {
    // Written as a plain JS string, `\.` would collapse to `.`.
    expect(config.matcher[0]).toContain("\\.(?:")
  })

  it.each([
    "/",
    "/sign-in",
    "/onboarding",
    "/brand/discover",
    // Ends in an excluded extension's letters but has no dot: still a page.
    "/brand/x/mexico",
    "/creator/packages/ico",
    "/brand/discover/svg",
  ])("runs on the page %s, so its session is refreshed", (path) => {
    expect(matcher.test(path)).toBe(true)
  })

  it.each([
    "/logo.png",
    "/icons/mark.svg",
    "/photo.jpg",
    "/favicon.ico",
    "/brand/x/pic.webp",
    "/_next/static/chunks/app.js",
    "/_next/image",
  ])("skips the static asset %s", (path) => {
    expect(matcher.test(path)).toBe(false)
  })
})

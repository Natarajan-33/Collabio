// @vitest-environment node
import { NextRequest, NextResponse } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { proxy } from "@/proxy"

const { updateSession } = vi.hoisted(() => ({ updateSession: vi.fn() }))
vi.mock("@/lib/supabase/proxy", () => ({ updateSession }))

/** What `updateSession` hands back: a pass-through response that carries fresh cookies. */
function refreshed(signedIn: boolean) {
  const response = NextResponse.next()
  response.cookies.set("sb-auth-token", "fresh", { path: "/", httpOnly: true })
  response.headers.set("cache-control", "private, no-store")
  updateSession.mockResolvedValue({ response, signedIn })
  return response
}

function request(path: string) {
  return new NextRequest(`http://localhost:3000${path}`)
}

describe("proxy", () => {
  beforeEach(() => updateSession.mockReset())

  it.each(["/brand/discover", "/creator/packages", "/onboarding", "/brand"])(
    "sends an anonymous visitor on %s to sign-in",
    async (path) => {
      refreshed(false)

      const res = await proxy(request(path))

      expect(res.status).toBe(307)
      expect(res.headers.get("location")).toBe(
        `http://localhost:3000/sign-in?next=${encodeURIComponent(path)}`
      )
    }
  )

  it("keeps the query string in next", async () => {
    refreshed(false)

    const res = await proxy(request("/brand/discover?q=tech"))

    expect(res.headers.get("location")).toBe(
      "http://localhost:3000/sign-in?next=%2Fbrand%2Fdiscover%3Fq%3Dtech"
    )
  })

  it("carries the refreshed cookies and cache headers onto the redirect", async () => {
    refreshed(false)

    const res = await proxy(request("/brand/discover"))

    expect(res.cookies.get("sb-auth-token")?.value).toBe("fresh")
    expect(res.headers.get("cache-control")).toBe("private, no-store")
    expect(res.headers.get("x-middleware-next")).toBeNull()
  })

  it("lets a signed-in user through, with the refreshed response", async () => {
    const response = refreshed(true)

    const res = await proxy(request("/creator/packages"))

    expect(res).toBe(response)
  })

  it.each(["/", "/sign-in", "/sign-up"])(
    "never redirects an anonymous visitor away from %s",
    async (path) => {
      const response = refreshed(false)

      const res = await proxy(request(path))

      expect(res).toBe(response)
    }
  )

  it("does not decide roles: a signed-in user is not redirected by role", async () => {
    const response = refreshed(true)

    expect(await proxy(request("/brand/discover"))).toBe(response)
  })
})

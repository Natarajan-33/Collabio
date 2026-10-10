import { NextRequest } from "next/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

const exchangeCodeForSession = vi.fn()

vi.mock("@/lib/supabase/server", () => ({
  createSupabaseServer: async () => ({ auth: { exchangeCodeForSession } }),
}))

import { GET } from "@/app/auth/callback/route"

const ORIGIN = "http://localhost:3000"

function callback(query: string) {
  return GET(new NextRequest(`${ORIGIN}/auth/callback${query}`))
}

describe("GET /auth/callback", () => {
  beforeEach(() => exchangeCodeForSession.mockReset())

  it("exchanges the confirmation code and lands on the app", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: null })

    const res = await callback("?code=abc123")

    expect(exchangeCodeForSession).toHaveBeenCalledWith("abc123")
    expect(res.status).toBe(307)
    expect(res.headers.get("location")).toBe(`${ORIGIN}/`)
  })

  it("keeps a safe in-app next path", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: null })

    const res = await callback("?code=abc&next=%2Fonboarding")

    expect(res.headers.get("location")).toBe(`${ORIGIN}/onboarding`)
  })

  it("never redirects to another site", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: null })

    const res = await callback("?code=abc&next=%2F%2Fevil.example")

    expect(res.headers.get("location")).toBe(`${ORIGIN}/`)
  })

  it("sends a failed or expired code to sign-in", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: new Error("expired") })

    const res = await callback("?code=stale")

    expect(res.headers.get("location")).toBe(`${ORIGIN}/sign-in?error=confirmation_failed`)
  })

  it("sends a request without a code to sign-in", async () => {
    const res = await callback("")

    expect(exchangeCodeForSession).not.toHaveBeenCalled()
    expect(res.headers.get("location")).toBe(`${ORIGIN}/sign-in?error=confirmation_failed`)
  })
})

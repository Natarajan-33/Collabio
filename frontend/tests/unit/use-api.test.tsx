import { renderHook } from "@testing-library/react"
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"

import { useApi } from "@/hooks/use-api"

const { router, auth } = vi.hoisted(() => ({
  router: { replace: vi.fn() },
  auth: { getSession: vi.fn(), refreshSession: vi.fn() },
}))

vi.mock("next/navigation", () => ({ useRouter: () => router }))
vi.mock("@/lib/supabase/browser", () => ({
  getSupabaseBrowser: () => ({ auth }),
}))

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("useApi", () => {
  // useApi builds its client once and openapi-fetch captures fetch at that moment, so the
  // same stub stays installed for the whole file.
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>()

  beforeAll(() => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://api.test")
    vi.stubGlobal("fetch", fetchMock)
  })

  afterAll(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  beforeEach(() => {
    fetchMock.mockReset()
    router.replace.mockReset()
    auth.getSession.mockReset()
    auth.refreshSession.mockReset()
    window.history.pushState({}, "", "/brand/discover")
  })

  it("signs requests with the Supabase session token", async () => {
    auth.getSession.mockResolvedValue({
      data: { session: { access_token: "abc" } },
    })
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { id: "u1" }))
    const { result } = renderHook(() => useApi())

    await result.current.GET("/api/v1/me")

    const request = fetchMock.mock.calls[0][0]
    expect(request.url).toBe("http://api.test/api/v1/me")
    expect(request.headers.get("Authorization")).toBe("Bearer abc")
  })

  it("sends the user to sign in, remembering the page, when the session is gone", async () => {
    auth.getSession.mockResolvedValue({
      data: { session: { access_token: "abc" } },
    })
    auth.refreshSession.mockResolvedValue({
      data: { session: null },
      error: new Error("refresh token revoked"),
    })
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "expired" }))
    const { result } = renderHook(() => useApi())

    await result.current.GET("/api/v1/me")

    expect(auth.refreshSession).toHaveBeenCalledTimes(1)
    expect(router.replace).toHaveBeenCalledWith(
      "/sign-in?next=%2Fbrand%2Fdiscover"
    )
  })

  it("retries with the refreshed session", async () => {
    auth.getSession
      .mockResolvedValueOnce({ data: { session: { access_token: "old" } } })
      .mockResolvedValueOnce({ data: { session: { access_token: "new" } } })
    auth.refreshSession.mockResolvedValue({
      data: { session: { access_token: "new" } },
      error: null,
    })
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(200, { id: "u1" }))
    const { result } = renderHook(() => useApi())

    const { data } = await result.current.GET("/api/v1/me")

    expect(data).toEqual({ id: "u1" })
    expect(fetchMock.mock.calls[1][0].headers.get("Authorization")).toBe(
      "Bearer new"
    )
    expect(router.replace).not.toHaveBeenCalled()
  })

  it("returns the same client to every caller", () => {
    const first = renderHook(() => useApi())
    const second = renderHook(() => useApi())

    expect(first.result.current).toBe(second.result.current)
  })
})

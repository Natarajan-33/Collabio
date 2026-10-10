// @vitest-environment node
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"

import { getMe } from "@/lib/auth/me"

const { auth } = vi.hoisted(() => ({ auth: { getSession: vi.fn() } }))
vi.mock("@/lib/supabase/server", () => ({
  createSupabaseServer: async () => ({ auth }),
}))

const ME = {
  user_id: "7b0e0e0a-0000-4000-8000-000000000001",
  email: "helper.creator@example.com",
  role: "creator",
  display_name: "Priya",
  brand: null,
  creator: null,
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function signedIn(token = "tok-1") {
  auth.getSession.mockResolvedValue({
    data: { session: { access_token: token } },
    error: null,
  })
}

describe("getMe", () => {
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
    auth.getSession.mockReset()
  })

  it("returns the signed-in user, sending the session token", async () => {
    signedIn("tok-9")
    fetchMock.mockResolvedValueOnce(jsonResponse(200, ME))

    const result = await getMe()

    expect(result).toEqual({ kind: "ok", me: ME })
    const request = fetchMock.mock.calls[0][0]
    expect(request.url).toBe("http://api.test/api/v1/me")
    expect(request.headers.get("authorization")).toBe("Bearer tok-9")
  })

  it("is anonymous without a session, and never calls the backend", async () => {
    auth.getSession.mockResolvedValue({ data: { session: null }, error: null })

    expect(await getMe()).toEqual({ kind: "anonymous" })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("is anonymous when the backend rejects the token", async () => {
    signedIn()
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "bad token" }))

    expect(await getMe()).toEqual({ kind: "anonymous" })
    // A 401 must not retry in a loop: one request, no refresh dance on the server.
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("is unavailable, not a crash, when the backend cannot be reached", async () => {
    signedIn()
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"))

    expect(await getMe()).toEqual({
      kind: "unavailable",
      reason: "unreachable",
    })
  })

  it("is unavailable when the request times out", async () => {
    signedIn()
    fetchMock.mockRejectedValueOnce(
      new DOMException("The operation timed out.", "TimeoutError")
    )

    expect(await getMe()).toEqual({
      kind: "unavailable",
      reason: "unreachable",
    })
  })

  it("passes a timeout signal so a hung backend cannot hang the page", async () => {
    signedIn()
    fetchMock.mockResolvedValueOnce(jsonResponse(200, ME))

    await getMe()

    expect(fetchMock.mock.calls[0][0].signal).toBeInstanceOf(AbortSignal)
  })

  it("is unavailable when the backend errors", async () => {
    signedIn()
    fetchMock.mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }))

    expect(await getMe()).toEqual({ kind: "unavailable", reason: "error" })
  })
})

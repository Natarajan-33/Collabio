import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { createApiClient } from "@/lib/api/client"

const BASE_URL = "http://api.test"

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("createApiClient", () => {
  // fetch is stubbed globally because openapi-fetch resolves it when the client is created.
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>()
  const getToken = vi.fn<() => Promise<string | null>>()
  const refresh = vi.fn<() => Promise<boolean>>()
  const onUnauthorized = vi.fn<(nextPath: string) => void>()

  const makeClient = () =>
    createApiClient({ baseUrl: BASE_URL, getToken, refresh, onUnauthorized })

  const sentRequest = (call: number): Request => fetchMock.mock.calls[call][0]

  beforeEach(() => {
    fetchMock.mockReset()
    getToken.mockReset().mockResolvedValue("t1")
    refresh.mockReset().mockResolvedValue(true)
    onUnauthorized.mockReset()
    vi.stubGlobal("fetch", fetchMock)
    window.history.pushState({}, "", "/brand/discover")
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("adds bearer token", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { id: "u1" }))

    const { data } = await makeClient().GET("/api/v1/me")

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(sentRequest(0).url).toBe(`${BASE_URL}/api/v1/me`)
    expect(sentRequest(0).headers.get("Authorization")).toBe("Bearer t1")
    expect(data).toEqual({ id: "u1" })
    expect(refresh).not.toHaveBeenCalled()
  })

  it("sends no Authorization header when signed out", async () => {
    getToken.mockResolvedValue(null)
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { status: "ok" }))

    await makeClient().GET("/api/v1/health")

    expect(sentRequest(0).headers.has("Authorization")).toBe(false)
  })

  it("401 refreshes once then retries", async () => {
    getToken.mockResolvedValueOnce("t1").mockResolvedValueOnce("t2")
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(200, { id: "u1" }))

    const { data, response } = await makeClient().GET("/api/v1/me")

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sentRequest(0).headers.get("Authorization")).toBe("Bearer t1")
    expect(sentRequest(1).headers.get("Authorization")).toBe("Bearer t2")
    expect(response.status).toBe(200)
    expect(data).toEqual({ id: "u1" })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it("401 refreshes once then redirects", async () => {
    getToken.mockResolvedValueOnce("t1").mockResolvedValueOnce("t2")
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "still no" }))

    const { error, response } = await makeClient().GET("/api/v1/me")

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(onUnauthorized).toHaveBeenCalledWith("/brand/discover")
    expect(response.status).toBe(401)
    expect(error).toEqual({ detail: "still no" })
  })

  it("redirects without retrying when the refresh fails", async () => {
    refresh.mockResolvedValue(false)
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))

    const { response } = await makeClient().GET("/api/v1/me")

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(onUnauthorized).toHaveBeenCalledWith("/brand/discover")
    expect(response.status).toBe(401)
  })

  it("replays the request body when retrying", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(
        jsonResponse(200, { query: "yoga", filters: {}, results: [] })
      )

    const { data } = await makeClient().POST("/api/v1/discovery/search", {
      body: { query: "yoga", limit: 12 },
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sentRequest(1).method).toBe("POST")
    expect(await sentRequest(1).json()).toEqual({ query: "yoga", limit: 12 })
    expect(data?.results).toEqual([])
  })

  it("leaves other errors alone", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(503, { detail: "down" }))

    const { response } = await makeClient().GET("/api/v1/me")

    expect(response.status).toBe(503)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(refresh).not.toHaveBeenCalled()
    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})

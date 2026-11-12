import { afterEach, describe, expect, it, vi } from "vitest"

import { publicUrl } from "@/lib/http/public-url"

const req = (url: string, headers: Record<string, string> = {}) =>
  ({ url, headers: new Headers(headers) }) as unknown as Request

describe("publicUrl", () => {
  afterEach(() => vi.unstubAllEnvs())

  it("prefers the configured public origin (Render sets RENDER_EXTERNAL_URL)", () => {
    vi.stubEnv("RENDER_EXTERNAL_URL", "https://collabio-web.onrender.com")
    const r = req("https://localhost:10000/api/demo-login?as=brand", { host: "localhost:10000" })
    expect(publicUrl("/brand/deals", r).toString()).toBe(
      "https://collabio-web.onrender.com/brand/deals"
    )
  })

  it("uses the proxy's forwarded host and protocol (Render: request.url is localhost:10000)", () => {
    const r = req("https://localhost:10000/api/demo-login?as=brand", {
      "x-forwarded-host": "collabio-web.onrender.com",
      "x-forwarded-proto": "https",
    })
    expect(publicUrl("/brand/deals", r).toString()).toBe(
      "https://collabio-web.onrender.com/brand/deals"
    )
  })

  it("takes the first value of a forwarded list and falls back to the host header", () => {
    const r = req("http://localhost:10000/x", {
      host: "collabio-web.onrender.com",
      "x-forwarded-proto": "https, http",
    })
    expect(publicUrl("/?demo=unavailable", r).toString()).toBe(
      "https://collabio-web.onrender.com/?demo=unavailable"
    )
  })

  it("keeps the request URL locally", () => {
    const r = req("http://localhost:3000/api/demo-login")
    expect(publicUrl("/brand/deals", r).toString()).toBe("http://localhost:3000/brand/deals")
  })
})

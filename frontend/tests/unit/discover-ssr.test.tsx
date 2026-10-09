// @vitest-environment node
import { renderToString } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import DiscoverPage from "@/app/brand/discover/page"
import ReviewPage from "@/app/brand/discover/review/page"

vi.mock("@/hooks/use-api", () => ({
  useApi: () => ({ POST: vi.fn(), GET: vi.fn() }),
}))
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }))

describe("Discover and Review on the server", () => {
  it("render without a browser: they start from session storage, which only the browser has", () => {
    const discover = renderToString(<DiscoverPage />)
    const review = renderToString(<ReviewPage />)

    // Neither reads storage nor draws the browser-only parts on the server.
    expect(discover).not.toContain("Selected creators")
    expect(discover).not.toContain("checkbox")
    expect(review).not.toContain("<table")
  })
})

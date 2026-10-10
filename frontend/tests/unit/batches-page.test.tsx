import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import BatchesPage from "@/app/brand/batches/page"

const h = vi.hoisted(() => ({
  api: { GET: vi.fn() },
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))

beforeEach(() => {
  h.api.GET.mockReset()
})

afterEach(cleanup)

describe("BatchesPage", () => {
  it("lists batches newest first with counts and links", async () => {
    h.api.GET.mockResolvedValue({
      data: [
        {
          id: "b-new",
          brief_id: "br-2",
          product_name: "Pods",
          launched_at: "2026-06-02T00:00:00Z",
          thread_count: 3,
          contacted: 2,
          replied: 1,
          countered: 0,
        },
        {
          id: "b-old",
          brief_id: "br-1",
          product_name: "Lamp",
          launched_at: "2026-01-01T00:00:00Z",
          thread_count: 1,
          contacted: 0,
          replied: 0,
          countered: 0,
        },
      ],
    })
    render(<BatchesPage />)
    expect(await screen.findByText("Pods")).toBeTruthy()
    const link = screen.getByRole("link", { name: "Pods" })
    expect(link.getAttribute("href")).toBe("/brand/batches/b-new")
    expect(screen.getByText("3")).toBeTruthy()
    expect(screen.getByText("2")).toBeTruthy()
  })

  it("shows the empty state with a discover link", async () => {
    h.api.GET.mockResolvedValue({ data: [] })
    render(<BatchesPage />)
    expect(await screen.findByText(/No launches yet/)).toBeTruthy()
    expect(screen.getByRole("link", { name: "Go to Discover" }).getAttribute("href")).toBe(
      "/brand/discover"
    )
  })
})

import { cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import BrandDealPage from "@/app/brand/deals/[id]/page"
import BrandDealsPage from "@/app/brand/deals/page"
import CreatorDealPage from "@/app/creator/deals/[id]/page"
import CreatorDealsPage from "@/app/creator/deals/page"
import type { components } from "@/lib/api/schema"

type DealView = components["schemas"]["DealView"]
type DealListItem = components["schemas"]["DealListItem"]

const h = vi.hoisted(() => ({
  api: { GET: vi.fn() },
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "deal-1" }),
}))

const LIST = "/api/v1/deals"
const ONE = "/api/v1/deals/{deal_id}"

const ITEM: DealListItem = {
  id: "deal-1",
  thread_id: "t1",
  counterpart_name: "Priya Shah",
  product_name: "Lumen Pods",
  videos: 3,
  price_cents: 120000,
  go_live_by: "2026-12-01",
  status: "booked",
  created_at: "2026-11-01T00:00:00Z",
}

const DEAL: DealView = {
  id: "deal-1",
  thread_id: "t1",
  batch_id: "batch-1",
  status: "booked",
  product_name: "Lumen Pods",
  terms: {
    videos: 3,
    format: "short_video",
    price_cents: 120000,
    go_live_by: "2026-12-01",
    conditions: ["No exclusivity"],
    addons: [],
  },
  milestones: [
    {
      id: "m1",
      seq: 1,
      title: "Video 1",
      amount_cents: 40000,
      due_date: "2026-12-01",
      status: "pending",
    },
    {
      id: "m2",
      seq: 2,
      title: "Video 2",
      amount_cents: 40000,
      due_date: "2026-12-01",
      status: "pending",
    },
    {
      id: "m3",
      seq: 3,
      title: "Video 3",
      amount_cents: 40000,
      due_date: "2026-12-01",
      status: "pending",
    },
  ],
  brand: { name: "Lumen", email: "hello@lumen.test" },
  creator: { name: "Priya Shah", email: "priya@example.com" },
  creator_handle: "priya",
  created_at: "2026-11-01T00:00:00Z",
}

beforeEach(() => {
  h.api.GET.mockReset()
})

afterEach(cleanup)

describe("brand deals", () => {
  it("lists booked deals with the creator, product, videos, price and go-live", async () => {
    h.api.GET.mockResolvedValue({ data: [ITEM] })
    render(<BrandDealsPage />)
    const link = await screen.findByRole("link", { name: /Priya Shah/ })
    expect(link.getAttribute("href")).toBe("/brand/deals/deal-1")
    expect(within(link).getByText("Lumen Pods")).toBeTruthy()
    expect(within(link).getByText(/3 videos/)).toBeTruthy()
    expect(within(link).getByText("$1,200").className).toMatch(/num/)
    expect(within(link).getByText(/Dec 1, 2026/)).toBeTruthy()
    expect(h.api.GET).toHaveBeenCalledWith(LIST)
  })

  it("says so when nothing is booked yet", async () => {
    h.api.GET.mockResolvedValue({ data: [] })
    render(<BrandDealsPage />)
    expect(await screen.findByText(/No booked deals yet/)).toBeTruthy()
  })

  it("says so when the deals cannot be loaded", async () => {
    h.api.GET.mockResolvedValue({ error: {}, data: undefined })
    render(<BrandDealsPage />)
    expect(await screen.findByText("Could not load your deals.")).toBeTruthy()
  })

  it("shows a deal with its payment schedule and the creator's email", async () => {
    h.api.GET.mockResolvedValue({ data: DEAL })
    render(<BrandDealPage />)
    expect(await screen.findByText("Payment schedule")).toBeTruthy()
    expect(h.api.GET).toHaveBeenCalledWith(ONE, {
      params: { path: { deal_id: "deal-1" } },
    })
    expect(screen.getByRole("heading", { name: /Lumen Pods/ })).toBeTruthy()
    const email = screen.getByRole("link", { name: "priya@example.com" })
    expect(email.getAttribute("href")).toBe("mailto:priya@example.com")
    expect(screen.queryByText("hello@lumen.test")).toBeNull()
    expect(
      screen.getByRole("link", { name: "View negotiation" }).getAttribute("href")
    ).toBe("/brand/batches/batch-1?thread=t1")
    expect(
      screen.getByRole("link", { name: "All deals" }).getAttribute("href")
    ).toBe("/brand/deals")
  })

  it("offers a way back when the deal is missing", async () => {
    h.api.GET.mockResolvedValue({ error: { detail: "not_found" } })
    render(<BrandDealPage />)
    expect(await screen.findByText("Could not load this deal.")).toBeTruthy()
    expect(
      screen.getByRole("link", { name: "All deals" }).getAttribute("href")
    ).toBe("/brand/deals")
  })
})

describe("creator deals", () => {
  it("lists booked deals with the brand", async () => {
    h.api.GET.mockResolvedValue({
      data: [{ ...ITEM, counterpart_name: "Lumen" }],
    })
    render(<CreatorDealsPage />)
    const link = await screen.findByRole("link", { name: /Lumen/ })
    expect(link.getAttribute("href")).toBe("/creator/deals/deal-1")
  })

  it("shows a deal with its payment schedule and the brand's email", async () => {
    h.api.GET.mockResolvedValue({ data: DEAL })
    render(<CreatorDealPage />)
    expect(await screen.findByText("Payment schedule")).toBeTruthy()
    expect(
      screen.getByRole("link", { name: "hello@lumen.test" }).getAttribute("href")
    ).toBe("mailto:hello@lumen.test")
    expect(screen.queryByText("priya@example.com")).toBeNull()
    expect(
      screen.getByRole("link", { name: "View offer" }).getAttribute("href")
    ).toBe("/creator/offers/t1")
  })
})

import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useEffect } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import CreatorOffersPage from "@/app/creator/offers/page"
import {
  VoiceScreenProvider,
  useVoiceRegistry,
  type VoiceRegistry,
} from "@/components/voice/voice-screen"
import type { components } from "@/lib/api/schema"

type OfferListItem = components["schemas"]["OfferListItem"]

const h = vi.hoisted(() => ({
  api: { GET: vi.fn() },
  router: { push: vi.fn() },
  ring: null as null | (() => void),
  creatorId: vi.fn(),
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("next/navigation", () => ({ useRouter: () => h.router }))
vi.mock("@/components/shell/creator-context", () => ({
  useCreatorId: () => h.creatorId(),
}))
vi.mock("@/lib/supabase/realtime", () => ({
  useCreatorDoorbell: (id: string | null, onRing: () => void) => {
    h.ring = id ? onRing : null
  },
}))

const FUTURE = new Date(Date.now() + 3 * 24 * 3_600_000 + 60_000).toISOString()

function offer(
  id: string,
  brand: string,
  over: Partial<OfferListItem> = {}
): OfferListItem {
  return {
    thread_id: id,
    brand: { id: `brand-${id}`, name: brand },
    product_name: `${brand} Pods`,
    status: "awaiting_reply",
    waiting_on: "creator",
    package: {
      id: "pkg",
      name: "Launch pack",
      content_type: "short_video",
      niche: "consumer_tech",
      volume_count: 3,
      volume_basis: "per_contract",
      base_price_cents: 120000,
      per_video_cents: 40000,
      one_liner: "3 shorts",
      lead_time_days: 14,
      preferred_channel: "email_first",
      addons: [],
    },
    delta_headline: "$250 under your rate",
    delta_flags: [],
    total_value_cents: 95000,
    go_live_by: "2026-11-14",
    expires_at: FUTURE,
    updated_at: "2026-10-01T00:00:00Z",
    fit_gap: 0.1,
    ...over,
  }
}

const COUNTS = { needs_you: 2, waiting: 1, booked: 0, closed: 4 }

type Init = { params?: { query?: Record<string, string> } }

/** Answers by path: counts, and the offers list for whatever tab/sort is asked. */
function serve(listFor: (tab: string | null, sort: string) => OfferListItem[]) {
  h.api.GET.mockImplementation(async (path: string, init?: Init) => {
    if (path === "/api/v1/offers/counts") return { data: COUNTS }
    const q = init?.params?.query ?? {}
    return { data: listFor(q.tab ?? null, q.sort ?? "fit") }
  })
}

function listCalls() {
  return h.api.GET.mock.calls
    .filter(([path]) => path === "/api/v1/offers")
    .map(([, init]) => (init as Init | undefined)?.params?.query)
}

let registry: VoiceRegistry | null = null
function Probe() {
  const value = useVoiceRegistry()
  useEffect(() => {
    registry = value
  })
  return null
}

function renderPage() {
  return render(
    <VoiceScreenProvider>
      <Probe />
      <CreatorOffersPage />
    </VoiceScreenProvider>
  )
}

beforeEach(() => {
  h.api.GET.mockReset()
  h.router.push.mockReset()
  h.ring = null
  h.creatorId.mockReset().mockReturnValue("creator-1")
})

afterEach(() => {
  registry = null
  cleanup()
})

describe("creator offers page", () => {
  it("renders the offer rows from the API", async () => {
    serve(() => [
      offer("t1", "Lumen", { delta_flags: ["below_base_price"] }),
      offer("t2", "Orbit", { status: "countered", expires_at: null }),
    ])
    renderPage()

    expect(await screen.findByText("Lumen")).toBeTruthy()
    expect(screen.getByText("Orbit")).toBeTruthy()
    expect(screen.getByText("Lumen Pods")).toBeTruthy()
    // Closest package, the delta, the flags, the total and the status.
    expect(screen.getAllByText("Launch pack").length).toBe(2)
    expect(screen.getAllByText("$250 under your rate").length).toBe(2)
    expect(screen.getByText("Below base price")).toBeTruthy()
    expect(screen.getAllByText("$950").length).toBe(2)
    expect(screen.getByText("Sent")).toBeTruthy()
    expect(screen.getByText("Countered")).toBeTruthy()
    // Only the offer that expires gets a badge.
    expect(document.querySelectorAll("[data-slot='expiry-badge']").length).toBe(
      1
    )
  })

  it("fetches the needs-you tab sorted by fit first", async () => {
    serve(() => [offer("t1", "Lumen")])
    renderPage()
    await screen.findByText("Lumen")

    expect(listCalls()[0]).toEqual({ tab: "needs_you", sort: "fit" })
  })

  it("shows each tab's count and switches tabs by refetching with tab=", async () => {
    const user = userEvent.setup()
    serve((tab) =>
      tab === "waiting"
        ? [offer("w1", "Quill", { status: "countered" })]
        : [offer("t1", "Lumen")]
    )
    renderPage()
    await screen.findByText("Lumen")

    const tabs = screen.getByRole("tablist")
    const labels = Array.from(tabs.querySelectorAll("[role='tab']")).map(
      (t) => t.textContent
    )
    expect(labels).toEqual(["Needs you2", "Waiting1", "Booked0", "Closed4"])
    expect(
      screen
        .getByRole("tab", { name: /Needs you/ })
        .getAttribute("aria-selected")
    ).toBe("true")

    await user.click(screen.getByRole("tab", { name: /Waiting/ }))

    expect(await screen.findByText("Quill")).toBeTruthy()
    expect(screen.queryByText("Lumen")).toBeNull()
    expect(listCalls().at(-1)).toEqual({ tab: "waiting", sort: "fit" })
    expect(
      screen.getByRole("tab", { name: /Waiting/ }).getAttribute("aria-selected")
    ).toBe("true")
  })

  it("sorts by revenue and timeline by refetching with sort=", async () => {
    const user = userEvent.setup()
    serve(() => [offer("t1", "Lumen")])
    renderPage()
    await screen.findByText("Lumen")

    await user.click(screen.getByRole("button", { name: "Revenue" }))
    await waitFor(() =>
      expect(listCalls().at(-1)).toEqual({ tab: "needs_you", sort: "revenue" })
    )

    await user.click(screen.getByRole("button", { name: "Timeline" }))
    await waitFor(() =>
      expect(listCalls().at(-1)).toEqual({ tab: "needs_you", sort: "timeline" })
    )
  })

  it("says what an empty tab means", async () => {
    const user = userEvent.setup()
    serve(() => [])
    renderPage()

    expect(
      await screen.findByText("Nothing needs your reply right now.")
    ).toBeTruthy()

    await user.click(screen.getByRole("tab", { name: /Booked/ }))
    expect(await screen.findByText("No booked deals yet.")).toBeTruthy()
  })

  it("opens the offer desk when a row is clicked", async () => {
    const user = userEvent.setup()
    serve(() => [offer("t1", "Lumen")])
    renderPage()

    await user.click(await screen.findByText("Lumen"))

    expect(h.router.push).toHaveBeenCalledWith("/creator/offers/t1")
  })

  it("refetches the list and the counts when the doorbell rings", async () => {
    serve(() => [offer("t1", "Lumen")])
    renderPage()
    await screen.findByText("Lumen")
    const before = h.api.GET.mock.calls.length

    await act(async () => {
      h.ring!()
    })

    await waitFor(() =>
      expect(h.api.GET.mock.calls.length).toBeGreaterThanOrEqual(before + 2)
    )
  })

  it("registers the offers screen and lists the visible offers", async () => {
    serve(() => [offer("t1", "Lumen"), offer("t2", "Orbit")])
    renderPage()
    await screen.findByText("Lumen")

    expect(registry?.current()?.screen).toBe("offers")
    expect(registry?.current()?.getContext().visible_offers).toEqual([
      { thread_id: "t1", brand_name: "Lumen" },
      { thread_id: "t2", brand_name: "Orbit" },
    ])
  })

  it("an open_offer intent navigates to that offer", async () => {
    serve(() => [offer("t1", "Lumen")])
    renderPage()
    await screen.findByText("Lumen")

    act(() => {
      registry?.current()?.onIntent({
        kind: "open_offer",
        heard: "open the Lumen offer",
        thread_id: "t1",
        suggestions: [],
      })
    })

    expect(h.router.push).toHaveBeenCalledWith("/creator/offers/t1")
  })

  it("ignores an open_offer for an offer that is not on screen", async () => {
    serve(() => [offer("t1", "Lumen")])
    renderPage()
    await screen.findByText("Lumen")

    act(() => {
      registry?.current()?.onIntent({
        kind: "open_offer",
        heard: "open the other one",
        thread_id: "nope",
        suggestions: [],
      })
    })

    expect(h.router.push).not.toHaveBeenCalled()
  })

  it("offers a retry when the list cannot load", async () => {
    const user = userEvent.setup()
    h.api.GET.mockImplementation(async (path: string) =>
      path === "/api/v1/offers/counts"
        ? { data: COUNTS }
        : { error: { detail: "boom" } }
    )
    renderPage()

    expect(await screen.findByText("Could not load your offers.")).toBeTruthy()
    serve(() => [offer("t1", "Lumen")])
    await user.click(screen.getByRole("button", { name: "Try again" }))
    expect(await screen.findByText("Lumen")).toBeTruthy()
  })

  it("shows the error state with a retry when a request rejects", async () => {
    const user = userEvent.setup()
    h.api.GET.mockRejectedValue(new TypeError("Failed to fetch"))
    renderPage()

    expect(await screen.findByText("Could not load your offers.")).toBeTruthy()
    serve(() => [offer("t1", "Lumen")])
    await user.click(screen.getByRole("button", { name: "Try again" }))
    expect(await screen.findByText("Lumen")).toBeTruthy()
  })

  it("does not update after it unmounts mid-request", async () => {
    let release: (value: unknown) => void = () => {}
    h.api.GET.mockImplementation(
      () => new Promise((resolve) => (release = resolve))
    )
    const errors = vi.spyOn(console, "error").mockImplementation(() => {})
    const { unmount } = renderPage()
    unmount()

    await act(async () => {
      release({ data: [] })
    })

    expect(errors).not.toHaveBeenCalled()
    errors.mockRestore()
  })
})

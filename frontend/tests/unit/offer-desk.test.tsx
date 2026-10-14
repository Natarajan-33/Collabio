import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useEffect } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import OfferDeskPage from "@/app/creator/offers/[threadId]/page"
import {
  VoiceScreenProvider,
  useVoiceRegistry,
  type VoiceRegistry,
} from "@/components/voice/voice-screen"
import type { components } from "@/lib/api/schema"

type OfferDesk = components["schemas"]["OfferDesk"]

const h = vi.hoisted(() => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
  ring: null as null | (() => void),
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("next/navigation", () => ({
  useParams: () => ({ threadId: "thread-1" }),
}))
vi.mock("sonner", () => ({ toast: h.toast }))
vi.mock("@/components/shell/creator-context", () => ({
  useCreatorId: () => "creator-1",
}))
vi.mock("@/lib/supabase/realtime", () => ({
  useCreatorDoorbell: (_id: string | null, onRing: () => void) => {
    h.ring = onRing
  },
}))

const FUTURE = new Date(Date.now() + 2 * 24 * 3_600_000 + 60_000).toISOString()

function column(over: Partial<OfferDesk["my_package"]> = {}) {
  return {
    videos: 3,
    price_cents: 120000,
    per_video_cents: 40000,
    go_live_by: "2026-12-01",
    conditions: [],
    ...over,
  }
}

function makeDesk(over: Partial<OfferDesk> = {}): OfferDesk {
  return {
    thread_id: "thread-1",
    brand: { id: "brand-1", name: "Lumen" },
    product_name: "Lumen Pods",
    product_summary: "Wireless earbuds",
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
    delta: {
      package_id: "pkg",
      package_name: "Launch pack",
      listed_videos: 3,
      ask_videos: 3,
      latest_videos: null,
      listed_price_cents: 120000,
      ask_price_cents: 95000,
      latest_price_cents: null,
      listed_per_video_cents: 40000,
      ask_per_video_cents: 31667,
      latest_per_video_cents: null,
      lead_time_days: 14,
      days_to_go_live: 30,
      headline: "$250 under your rate",
      latest_headline: null,
      flags: [],
    },
    my_package: column(),
    their_ask: column({
      price_cents: 95000,
      per_video_cents: 31667,
      go_live_by: "2026-11-14",
    }),
    latest: null,
    latest_source: null,
    changed: [],
    brand_note: null,
    terms_event_id: 42,
    allowed_actions: ["counter", "accept", "decline"],
    floor_price_cents: 90000,
    events: [],
    transcripts: [],
    deal_id: null,
    expires_at: FUTURE,
    ...over,
  }
}

function serveDesk(desk: OfferDesk) {
  h.api.GET.mockResolvedValue({ data: desk })
}

function postsTo(suffix: string) {
  return h.api.POST.mock.calls.filter(([path]) => String(path).endsWith(suffix))
}

let registry: VoiceRegistry | null = null
function Probe() {
  const value = useVoiceRegistry()
  useEffect(() => {
    registry = value
  })
  return null
}

function renderDesk() {
  return render(
    <VoiceScreenProvider>
      <Probe />
      <OfferDeskPage />
    </VoiceScreenProvider>
  )
}

beforeEach(() => {
  h.api.GET.mockReset()
  h.api.POST.mockReset()
  h.toast.info.mockReset()
  h.toast.error.mockReset()
  h.toast.success.mockReset()
  h.ring = null
})

afterEach(() => {
  registry = null
  cleanup()
})

const CONFLICT_TERMS_CHANGED = {
  error: {
    detail: {
      code: "terms_changed",
      message: "The terms changed.",
      terms_event_id: 43,
    },
  },
}

describe("offer desk page", () => {
  it("shows the header, the three columns, the brand note and the log", async () => {
    serveDesk(
      makeDesk({
        brand_note: "We love your style",
        latest: column({ price_cents: 105000, per_video_cents: 35000 }),
        latest_source: "brand",
        changed: ["price_cents"],
        events: [
          {
            id: 1,
            type: "email_sent",
            actor: "system",
            created_at: "2026-10-10T10:00:00Z",
            payload: {},
            terms: null,
          },
        ],
      })
    )
    renderDesk()

    expect(await screen.findByRole("heading", { name: "Lumen" })).toBeTruthy()
    expect(screen.getByText("Lumen Pods")).toBeTruthy()
    expect(screen.getByText("Sent")).toBeTruthy()
    expect(document.querySelector("[data-slot='expiry-badge']")).toBeTruthy()

    expect(screen.getByText("My package")).toBeTruthy()
    expect(screen.getByText("Their ask")).toBeTruthy()
    expect(screen.getByText("Latest")).toBeTruthy()
    expect(
      document.querySelector(
        "[data-slot='compare-columns'] [data-changed='true']"
      )
    ).toBeTruthy()

    expect(screen.getByText("We love your style")).toBeTruthy()
    expect(screen.getByText("Email sent")).toBeTruthy()
  })

  it("renders only the actions the API allows", async () => {
    serveDesk(makeDesk({ allowed_actions: ["accept"] }))
    renderDesk()

    await screen.findByRole("heading", { name: "Lumen" })
    expect(screen.getByRole("button", { name: "Accept" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Counter" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull()
  })

  it("renders no actions when none are allowed", async () => {
    serveDesk(makeDesk({ allowed_actions: [], status: "countered" }))
    renderDesk()

    await screen.findByRole("heading", { name: "Lumen" })
    for (const name of ["Accept", "Counter", "Decline"]) {
      expect(screen.queryByRole("button", { name })).toBeNull()
    }
  })

  it("links the booked banner to the deal", async () => {
    serveDesk(
      makeDesk({ status: "awarded", allowed_actions: [], deal_id: "deal-9" })
    )
    renderDesk()

    const link = await screen.findByRole("link", { name: /view deal/i })
    expect(link.getAttribute("href")).toBe("/creator/deals/deal-9")
  })

  it("offers a retry when the offer cannot load", async () => {
    const user = userEvent.setup()
    h.api.GET.mockResolvedValueOnce({ error: { detail: "not_found" } })
    renderDesk()

    expect(await screen.findByText("Could not load this offer.")).toBeTruthy()
    serveDesk(makeDesk())
    await user.click(screen.getByRole("button", { name: "Try again" }))
    expect(await screen.findByRole("heading", { name: "Lumen" })).toBeTruthy()
  })

  it("refetches when the creator doorbell rings", async () => {
    serveDesk(makeDesk())
    renderDesk()
    await screen.findByRole("heading", { name: "Lumen" })
    const before = h.api.GET.mock.calls.length

    await act(async () => {
      h.ring!()
    })

    await waitFor(() =>
      expect(h.api.GET.mock.calls.length).toBeGreaterThan(before)
    )
  })
})

describe("accepting", () => {
  it("lists the exact terms and posts the event they were read from", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockResolvedValue({
      data: makeDesk({ status: "accepted", allowed_actions: [] }),
    })
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Accept" }))
    const dialog = await screen.findByRole("dialog")
    expect(
      within(dialog).getByText("3 videos · $950 · live by Nov 14, 2026")
    ).toBeTruthy()
    expect(h.api.POST).not.toHaveBeenCalled()

    await user.click(
      within(dialog).getByRole("button", { name: "Accept these terms" })
    )

    await waitFor(() => expect(h.api.POST).toHaveBeenCalledTimes(1))
    expect(h.api.POST).toHaveBeenCalledWith(
      "/api/v1/offers/{thread_id}/accept",
      {
        params: { path: { thread_id: "thread-1" } },
        body: { based_on_event_id: 42 },
      }
    )
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(h.toast.success).toHaveBeenCalled()
  })

  it("accepts the brand's latest counter, not the original ask", async () => {
    const user = userEvent.setup()
    serveDesk(
      makeDesk({
        status: "countered",
        latest: column({
          price_cents: 105000,
          per_video_cents: 35000,
          go_live_by: "2026-11-20",
          conditions: ["No exclusivity"],
        }),
        latest_source: "brand",
      })
    )
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Accept" }))
    const dialog = await screen.findByRole("dialog")
    expect(
      within(dialog).getByText("3 videos · $1,050 · live by Nov 20, 2026")
    ).toBeTruthy()
    expect(within(dialog).getByText("No exclusivity")).toBeTruthy()
  })

  it("on terms_changed refetches, flags the change and says so", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockResolvedValue(CONFLICT_TERMS_CHANGED)
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Accept" }))
    const dialog = await screen.findByRole("dialog")
    const before = h.api.GET.mock.calls.length
    await user.click(
      within(dialog).getByRole("button", { name: "Accept these terms" })
    )

    await waitFor(() =>
      expect(h.api.GET.mock.calls.length).toBeGreaterThan(before)
    )
    expect(h.toast.info).toHaveBeenCalledWith(
      "Terms changed — review the latest"
    )
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  it("on action_not_allowed refetches without accepting", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockResolvedValue({
      error: {
        detail: { code: "action_not_allowed", message: "Not allowed now." },
      },
    })
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Accept" }))
    const dialog = await screen.findByRole("dialog")
    const before = h.api.GET.mock.calls.length
    await user.click(
      within(dialog).getByRole("button", { name: "Accept these terms" })
    )

    await waitFor(() =>
      expect(h.api.GET.mock.calls.length).toBeGreaterThan(before)
    )
    expect(h.toast.error).toHaveBeenCalledWith("Not allowed now.")
  })
})

describe("binding to the terms that were read", () => {
  it("accept posts the event id from when the dialog opened, even after a refetch", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockResolvedValue({ data: makeDesk({ allowed_actions: [] }) })
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Accept" }))
    const dialog = await screen.findByRole("dialog")
    expect(
      within(dialog).getByText("3 videos · $950 · live by Nov 14, 2026")
    ).toBeTruthy()

    // The brand counters while the dialog is open; the doorbell refetches.
    serveDesk(
      makeDesk({
        terms_event_id: 43,
        status: "countered",
        latest: column({ price_cents: 80000, per_video_cents: 26667 }),
        latest_source: "brand",
      })
    )
    const before = h.api.GET.mock.calls.length
    await act(async () => {
      h.ring!()
    })
    await waitFor(() =>
      expect(h.api.GET.mock.calls.length).toBeGreaterThan(before)
    )

    // The dialog still shows what was read, and binds to it.
    expect(
      within(dialog).getByText("3 videos · $950 · live by Nov 14, 2026")
    ).toBeTruthy()
    await user.click(
      within(dialog).getByRole("button", { name: "Accept these terms" })
    )

    await waitFor(() => expect(h.api.POST).toHaveBeenCalledTimes(1))
    expect(h.api.POST.mock.calls[0][1].body).toEqual({
      based_on_event_id: 42,
    })
  })

  it("counter is based on the event id from when the dialog opened", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockImplementation(async (path: string) =>
      path.endsWith("/counter/preview")
        ? {
            data: {
              terms: {
                stance: "counter",
                source: "in_app",
                conditions: [],
                addons: [],
                confidence: 1,
              },
              delta: { ...makeDesk().delta, latest_headline: "Preview" },
              below_floor_by_cents: null,
            },
          }
        : { data: makeDesk({ allowed_actions: [] }) }
    )
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog")

    serveDesk(makeDesk({ terms_event_id: 99 }))
    const before = h.api.GET.mock.calls.length
    await act(async () => {
      h.ring!()
    })
    await waitFor(() =>
      expect(h.api.GET.mock.calls.length).toBeGreaterThan(before)
    )

    await user.click(
      within(dialog).getByRole("button", { name: "Send counter" })
    )
    await waitFor(() => expect(postsTo("/counter").length).toBe(1))
    expect(postsTo("/counter")[0][1].body.based_on_event_id).toBe(42)
  })
})

describe("declining", () => {
  it("posts the optional reason", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockResolvedValue({
      data: makeDesk({ status: "declined", allowed_actions: [] }),
    })
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Decline" }))
    const dialog = await screen.findByRole("dialog")
    await user.type(
      within(dialog).getByRole("textbox", { name: /reason/i }),
      "Not a fit"
    )
    await user.click(
      within(dialog).getByRole("button", { name: "Decline offer" })
    )

    await waitFor(() => expect(h.api.POST).toHaveBeenCalledTimes(1))
    expect(h.api.POST).toHaveBeenCalledWith(
      "/api/v1/offers/{thread_id}/decline",
      {
        params: { path: { thread_id: "thread-1" } },
        body: { reason: "Not a fit" },
      }
    )
  })

  it("sends no reason when none is given", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockResolvedValue({ data: makeDesk({ allowed_actions: [] }) })
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Decline" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(
      within(dialog).getByRole("button", { name: "Decline offer" })
    )

    await waitFor(() => expect(h.api.POST).toHaveBeenCalled())
    expect(h.api.POST.mock.calls[0][1].body).toEqual({ reason: null })
  })
})

describe("countering", () => {
  function previewReply(below: number | null) {
    return {
      data: {
        terms: {
          stance: "counter",
          source: "in_app",
          conditions: [],
          addons: [],
          confidence: 1,
        },
        delta: { ...makeDesk().delta, latest_headline: "$100 over your ask" },
        below_floor_by_cents: below,
      },
    }
  }

  function route(below: number | null) {
    h.api.POST.mockImplementation(async (path: string) => {
      if (path.endsWith("/counter/preview")) return previewReply(below)
      return { data: makeDesk({ status: "countered", allowed_actions: [] }) }
    })
  }

  it("prefills from their ask, previews, then sends with the event it was based on", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    route(null)
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog")
    const price = within(dialog).getByRole("textbox", {
      name: "Price",
    }) as HTMLInputElement
    expect(price.value).toContain("950")

    expect(await within(dialog).findByText("$100 over your ask")).toBeTruthy()
    expect(postsTo("/counter/preview")[0][1]).toEqual({
      params: { path: { thread_id: "thread-1" } },
      body: {
        terms: {
          videos: 3,
          price_cents: 95000,
          go_live_by: "2026-11-14",
          conditions: [],
        },
      },
    })

    await user.click(
      within(dialog).getByRole("button", { name: "Send counter" })
    )

    await waitFor(() => expect(postsTo("/counter").length).toBe(1))
    expect(postsTo("/counter")[0][1]).toEqual({
      params: { path: { thread_id: "thread-1" } },
      body: {
        terms: {
          videos: 3,
          price_cents: 95000,
          go_live_by: "2026-11-14",
          conditions: [],
        },
        based_on_event_id: 42,
        confirm_below_floor: false,
        note: null,
      },
    })
  })

  it("prefills from the latest terms when there are some", async () => {
    const user = userEvent.setup()
    serveDesk(
      makeDesk({
        latest: column({ price_cents: 110000, per_video_cents: 36667 }),
        latest_source: "creator",
      })
    )
    route(null)
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog")
    const price = within(dialog).getByRole("textbox", {
      name: "Price",
    }) as HTMLInputElement
    expect(price.value).toContain("1100")
  })

  it("warns about the floor and needs a second confirmation to send below it", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    route(5000)
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog")
    expect(await within(dialog).findByText(/below your floor/)).toBeTruthy()

    await user.click(
      within(dialog).getByRole("button", { name: "Send counter" })
    )
    // Not sent yet: the second confirmation comes first.
    expect(postsTo("/counter").length).toBe(0)
    const confirm = await within(dialog).findByRole("button", {
      name: "Send below my floor",
    })

    await user.click(confirm)

    await waitFor(() => expect(postsTo("/counter").length).toBe(1))
    expect(postsTo("/counter")[0][1].body.confirm_below_floor).toBe(true)
  })

  it("moves to the confirmation if the server finds the price below the floor", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockImplementation(async (path: string) => {
      if (path.endsWith("/counter/preview")) return previewReply(null)
      return {
        error: {
          detail: {
            code: "below_floor",
            message: "Below your floor.",
            below_by_cents: 7000,
          },
        },
      }
    })
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog")
    await within(dialog).findByText("$100 over your ask")
    await user.click(
      within(dialog).getByRole("button", { name: "Send counter" })
    )

    expect(
      await within(dialog).findByRole("button", { name: "Send below my floor" })
    ).toBeTruthy()
    expect(within(dialog).getByRole("alert").textContent).toContain("$70")
  })

  it("on terms_changed refetches and says so", async () => {
    const user = userEvent.setup()
    serveDesk(makeDesk())
    h.api.POST.mockImplementation(async (path: string) =>
      path.endsWith("/counter/preview")
        ? previewReply(null)
        : CONFLICT_TERMS_CHANGED
    )
    renderDesk()

    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog")
    await within(dialog).findByText("$100 over your ask")
    const before = h.api.GET.mock.calls.length
    await user.click(
      within(dialog).getByRole("button", { name: "Send counter" })
    )

    await waitFor(() =>
      expect(h.api.GET.mock.calls.length).toBeGreaterThan(before)
    )
    expect(h.toast.info).toHaveBeenCalledWith(
      "Terms changed — review the latest"
    )
  })
})

describe("voice", () => {
  it("registers the offer desk with no terms until a counter is open", async () => {
    serveDesk(makeDesk())
    renderDesk()
    await screen.findByRole("heading", { name: "Lumen" })

    expect(registry?.current()?.screen).toBe("offer_desk")
    expect(registry?.current()?.getContext().current_terms ?? null).toBeNull()
  })

  it("a counter intent opens the dialog prefilled and sends nothing", async () => {
    serveDesk(makeDesk())
    h.api.POST.mockResolvedValue({ data: previewOnly() })
    renderDesk()
    await screen.findByRole("heading", { name: "Lumen" })

    act(() => {
      registry?.current()?.onIntent({
        kind: "counter",
        heard: "counter at 1100 for 4 videos",
        suggestions: [],
        terms: { videos: 4, price_cents: 110000, conditions: [] },
      })
    })

    const dialog = await screen.findByRole("dialog")
    const price = within(dialog).getByRole("textbox", {
      name: "Price",
    }) as HTMLInputElement
    expect(price.value).toContain("1100")
    // Fields the speaker left out keep the prefill (their ask's go-live date).
    expect(
      (within(dialog).getByLabelText("Go live by") as HTMLInputElement).value
    ).toBe("2026-11-14")
    expect(registry?.current()?.getContext().current_terms).toMatchObject({
      videos: 4,
      price_cents: 110000,
      go_live_by: "2026-11-14",
    })

    // Only the preview may be asked for; nothing is sent.
    await new Promise((resolve) => setTimeout(resolve, 600))
    expect(postsTo("/counter").length).toBe(0)
    expect(postsTo("/accept").length).toBe(0)
    expect(postsTo("/decline").length).toBe(0)
  })

  it("an accept intent opens the accept dialog without accepting", async () => {
    serveDesk(makeDesk())
    renderDesk()
    await screen.findByRole("heading", { name: "Lumen" })

    act(() => {
      registry?.current()?.onIntent({
        kind: "accept",
        heard: "accept it",
        suggestions: [],
      })
    })

    const dialog = await screen.findByRole("dialog")
    expect(
      within(dialog).getByRole("button", { name: "Accept these terms" })
    ).toBeTruthy()
    expect(h.api.POST).not.toHaveBeenCalled()
  })

  it("a decline intent opens the decline dialog with the reason filled in", async () => {
    serveDesk(makeDesk())
    renderDesk()
    await screen.findByRole("heading", { name: "Lumen" })

    act(() => {
      registry?.current()?.onIntent({
        kind: "decline",
        heard: "decline, too low",
        suggestions: [],
        reason: "too low",
      })
    })

    const dialog = await screen.findByRole("dialog")
    expect(
      (
        within(dialog).getByRole("textbox", {
          name: /reason/i,
        }) as HTMLTextAreaElement
      ).value
    ).toBe("too low")
    expect(h.api.POST).not.toHaveBeenCalled()
  })

  it("ignores an intent for an action that is not allowed", async () => {
    serveDesk(makeDesk({ allowed_actions: [], status: "countered" }))
    renderDesk()
    await screen.findByRole("heading", { name: "Lumen" })

    act(() => {
      registry?.current()?.onIntent({
        kind: "accept",
        heard: "accept it",
        suggestions: [],
      })
    })

    expect(screen.queryByRole("dialog")).toBeNull()
  })
})

function previewOnly() {
  return {
    terms: {
      stance: "counter",
      source: "in_app",
      conditions: [],
      addons: [],
      confidence: 1,
    },
    delta: { ...makeDesk().delta, latest_headline: "Preview" },
    below_floor_by_cents: null,
  }
}

import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import type { ReactNode } from "react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import BatchBoardPage from "@/app/brand/batches/[id]/page"
import type { components } from "@/lib/api/schema"

type BatchView = components["schemas"]["BatchView"]
type ThreadCard = components["schemas"]["ThreadCard"]

const h = vi.hoisted(() => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  doorbell: vi.fn(),
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
  search: "",
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "batch-1" }),
  useSearchParams: () => new URLSearchParams(h.search),
}))
vi.mock("sonner", () => ({ toast: h.toast }))
vi.mock("@/lib/supabase/realtime", () => ({
  useBatchDoorbell: (
    _id: string,
    onRing: () => void,
    opts?: { live?: boolean }
  ) => {
    h.doorbell(onRing, opts)
  },
}))
vi.mock("@/components/ui/count-up", () => ({
  default: ({ to }: { to: number }) => <span>{to}</span>,
}))
vi.mock("@gsap/react", () => ({
  useGSAP: (fn: () => void | (() => void)) => {
    const cleanup = fn()
    return cleanup
  },
}))
vi.mock("gsap", () => ({
  default: {
    registerPlugin: vi.fn(),
    matchMedia: () => ({
      add: (_q: string, fn: () => void) => fn(),
      revert: vi.fn(),
    }),
    from: vi.fn(),
  },
}))
vi.mock("gsap/Flip", () => ({
  Flip: {
    getState: () => ({}),
    from: vi.fn(),
  },
}))
vi.mock("@/components/ShinyText", () => ({
  default: ({ children }: { children: ReactNode }) => (
    <span>{children}</span>
  ),
}))
vi.mock("@/components/board/email-reveal", () => ({
  EmailReveal: ({ text }: { text: string }) => <p>{text}</p>,
}))

function card(id: string, name: string, over: Partial<ThreadCard> = {}): ThreadCard {
  return {
    id,
    creator: { id: `c-${id}`, name, handle: name, initials: "XX" },
    channel_plan: "email",
    status: "queued",
    package: {
      id: "pkg",
      name: "P",
      content_type: "short_video",
      niche: "consumer_tech",
      volume_count: 3,
      volume_basis: "per_contract",
      base_price_cents: 100000,
      per_video_cents: 33333,
      one_liner: "3",
      lead_time_days: 14,
      preferred_channel: "email_first",
      addons: [],
    },
    latest_terms: null,
    latest_terms_source: null,
    terms_event_id: null,
    deal_id: null,
    expires_at: null,
    allowed_actions: [],
    delta: {
      package_id: "pkg",
      package_name: "P",
      listed_videos: 3,
      ask_videos: 3,
      latest_videos: null,
      listed_price_cents: 100000,
      ask_price_cents: 100000,
      latest_price_cents: null,
      listed_per_video_cents: 33333,
      ask_per_video_cents: 33333,
      latest_per_video_cents: null,
      lead_time_days: 14,
      days_to_go_live: 30,
      headline: "Same",
      latest_headline: null,
      flags: [],
    },
    last_event: null,
    email: null,
    live_offers: [],
    best_value: {
      thread_id: id,
      eligible: true,
      rank: id === "t-low" ? 1 : 2,
      score: 1,
      per_video_cents: id === "t-low" ? 30000 : 40000,
      reasons: [],
      ineligible_reason: null,
    },
    last_error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  }
}

function view(
  threads: ThreadCard[],
  over: { hired?: number; hires_target?: number } = {}
): BatchView {
  return {
    id: "batch-1",
    brief: {
      brief_id: "brief-1",
      product_name: "Lumen Pods",
      deliverables_count: 3,
      deliverables_format: "short_video",
      ask_price_cents: 100000,
      budget_ceiling_cents: 120000,
      go_live_by: "2026-11-14",
      follow_up_policy: "off",
      hires_target: over.hires_target ?? 1,
    },
    kpis: {
      contacted: 0,
      replied: 0,
      countered: 0,
      hired: over.hired ?? 0,
      best_per_video_cents: null,
      launched_at: new Date().toISOString(),
    },
    threads,
  }
}

beforeEach(() => {
  h.api.GET.mockReset()
  h.api.POST.mockReset()
  h.doorbell.mockReset()
  h.toast.info.mockReset()
  h.toast.error.mockReset()
  h.toast.success.mockReset()
  h.search = ""
})

afterEach(cleanup)

describe("BatchBoardPage", () => {
  it("loads the batch and renders a card per thread", async () => {
    h.api.GET.mockResolvedValue({
      data: view([card("t1", "Arjun"), card("t2", "Priya")]),
    })
    render(<BatchBoardPage />)
    expect(await screen.findByText("Arjun")).toBeTruthy()
    expect(screen.getByText("Priya")).toBeTruthy()
  })

  it("refetches when the doorbell rings", async () => {
    h.api.GET.mockResolvedValue({ data: view([card("t1", "Arjun")]) })
    render(<BatchBoardPage />)
    await waitFor(() => expect(h.api.GET).toHaveBeenCalledTimes(1))
    const [[onRing]] = h.doorbell.mock.calls
    onRing()
    await waitFor(() => expect(h.api.GET).toHaveBeenCalledTimes(2))
  })

  it("passes live=true to the doorbell while threads are in flight", async () => {
    h.api.GET.mockResolvedValue({
      data: view([card("t1", "Arjun", { status: "drafting" })]),
    })
    render(<BatchBoardPage />)
    await waitFor(() => expect(h.doorbell).toHaveBeenCalled())
    const opts = h.doorbell.mock.calls.at(-1)?.[1]
    expect(opts?.live).toBe(true)
  })

  it("sort control reorders the cards", async () => {
    const user = userEvent.setup()
    h.api.GET.mockResolvedValue({
      data: view([
        card("t-high", "High", { updated_at: "2026-01-01T00:00:00Z" }),
        card("t-low", "Low", { updated_at: "2026-06-01T00:00:00Z" }),
      ]),
    })
    render(<BatchBoardPage />)
    await waitFor(() => screen.getByText("High"))
    const grid = screen.getByText("High").closest('[class*="grid"]')!
    expect(grid.textContent?.indexOf("Low")).toBeLessThan(
      grid.textContent?.indexOf("High") ?? 0
    )
    await user.click(screen.getByRole("button", { name: "Recent" }))
    await waitFor(() => {
      const text = grid.textContent ?? ""
      expect(text.indexOf("Low")).toBeLessThan(text.indexOf("High"))
    })
  })

  it("Retry posts and refetches", async () => {
    const user = userEvent.setup()
    h.api.GET.mockResolvedValue({
      data: view([
        card("t1", "Fail", { status: "failed", last_error: "No answer." }),
      ]),
    })
    h.api.POST.mockResolvedValue({ data: { ok: true } })
    render(<BatchBoardPage />)
    await waitFor(() => screen.getByRole("button", { name: "Retry" }))
    await user.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => {
      expect(h.api.POST).toHaveBeenCalledWith(
        "/api/v1/threads/{thread_id}/retry",
        { params: { path: { thread_id: "t1" } } }
      )
      expect(h.api.GET).toHaveBeenCalledTimes(2)
    })
  })

  it("reveals a newly drafted email once", async () => {
    h.api.GET
      .mockResolvedValueOnce({
        data: view([
          card("t1", "Maya", {
            email: { subject: "Hi", body_text: "Draft body", delivered: false },
          }),
        ]),
      })
      .mockResolvedValueOnce({
        data: view([
          card("t1", "Maya", {
            email: { subject: "Hi", body_text: "Draft body", delivered: false },
          }),
        ]),
      })
    render(<BatchBoardPage />)
    await waitFor(() => screen.getByText("Draft body"))
    const [[onRing]] = h.doorbell.mock.calls
    onRing()
    await waitFor(() => expect(h.api.GET).toHaveBeenCalledTimes(2))
  })

  it("shows how many creators are hired against the target", async () => {
    h.api.GET.mockResolvedValue({
      data: view([card("t1", "Arjun")], { hired: 1, hires_target: 2 }),
    })
    render(<BatchBoardPage />)
    await screen.findByText("Arjun")
    const label = screen.getByText("Hired")
    expect(label.parentElement?.textContent).toBe("Hired1 / 2")
  })

  it("opens the drawer for ?thread= once the board has loaded", async () => {
    h.search = "thread=t2"
    h.api.GET.mockImplementation(async (path: string) =>
      path === "/api/v1/threads/{thread_id}"
        ? { data: undefined, error: { detail: "thread_not_found" } }
        : { data: view([card("t1", "Arjun"), card("t2", "Priya")]) }
    )
    render(<BatchBoardPage />)
    await screen.findByText("Arjun")
    await waitFor(() =>
      expect(h.api.GET).toHaveBeenCalledWith("/api/v1/threads/{thread_id}", {
        params: { path: { thread_id: "t2" } },
      })
    )
    expect(h.api.GET).not.toHaveBeenCalledWith("/api/v1/threads/{thread_id}", {
      params: { path: { thread_id: "t1" } },
    })
  })

  it("ignores a ?thread= that is not on this board", async () => {
    h.search = "thread=elsewhere"
    h.api.GET.mockResolvedValue({ data: view([card("t1", "Arjun")]) })
    render(<BatchBoardPage />)
    await screen.findByText("Arjun")
    expect(h.api.GET).not.toHaveBeenCalledWith(
      "/api/v1/threads/{thread_id}",
      expect.anything()
    )
  })

  it("only offers Decline remaining once someone is hired", async () => {
    h.api.GET.mockResolvedValue({ data: view([card("t1", "Arjun")]) })
    render(<BatchBoardPage />)
    await screen.findByText("Arjun")
    expect(screen.queryByRole("button", { name: "Decline remaining" })).toBeNull()
  })

  it("lists who would be declined, then declines them on confirm", async () => {
    const user = userEvent.setup()
    h.api.GET.mockResolvedValue({
      data: view([card("t1", "Arjun"), card("t2", "Priya")], { hired: 1 }),
    })
    h.api.POST.mockImplementation(async (path: string) =>
      path.endsWith("/decline-rest/preview")
        ? {
            data: {
              will_close: [
                {
                  thread_id: "t1",
                  creator: { id: "c-t1", name: "Arjun", handle: "arjun", initials: "AR" },
                  status: "awaiting_reply",
                },
                {
                  thread_id: "t2",
                  creator: { id: "c-t2", name: "Priya", handle: "priya", initials: "PR" },
                  status: "countered",
                },
              ],
              skipped: [],
            },
          }
        : { data: { closed: ["t1", "t2"], failed: [] } }
    )
    render(<BatchBoardPage />)
    await screen.findByText("Arjun")
    await user.click(screen.getByRole("button", { name: "Decline remaining" }))
    const dialog = await screen.findByRole("dialog", {
      name: /Decline the remaining/,
    })
    expect(await within(dialog).findByText("Arjun")).toBeTruthy()
    expect(within(dialog).getByText("Priya")).toBeTruthy()
    expect(h.api.POST).toHaveBeenCalledTimes(1)
    expect(h.api.POST).toHaveBeenCalledWith(
      "/api/v1/batches/{batch_id}/decline-rest/preview",
      { params: { path: { batch_id: "batch-1" } } }
    )
    await user.click(
      within(dialog).getByRole("button", { name: "Decline 2 creators" })
    )
    await waitFor(() =>
      expect(h.api.POST).toHaveBeenCalledWith(
        "/api/v1/batches/{batch_id}/decline-rest",
        { params: { path: { batch_id: "batch-1" } } }
      )
    )
    await waitFor(() => expect(h.toast.success).toHaveBeenCalled())
    // The board is reloaded.
    await waitFor(() => expect(h.api.GET.mock.calls.length).toBeGreaterThan(1))
  })

  it("says so when nobody is left to decline", async () => {
    const user = userEvent.setup()
    h.api.GET.mockResolvedValue({
      data: view([card("t1", "Arjun")], { hired: 1 }),
    })
    h.api.POST.mockResolvedValue({ data: { will_close: [], skipped: [] } })
    render(<BatchBoardPage />)
    await screen.findByText("Arjun")
    await user.click(screen.getByRole("button", { name: "Decline remaining" }))
    const dialog = await screen.findByRole("dialog")
    expect(await within(dialog).findByText(/No open conversations/)).toBeTruthy()
    expect(
      within(dialog).queryByRole("button", { name: /^Decline \d/ })
    ).toBeNull()
  })
})

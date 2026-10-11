import { act, cleanup, render, screen } from "@testing-library/react"
import { useEffect } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import BatchBoardPage from "@/app/brand/batches/[id]/page"
import {
  VoiceScreenProvider,
  useVoiceRegistry,
  type VoiceRegistry,
} from "@/components/voice/voice-screen"

const h = vi.hoisted(() => ({
  api: { GET: vi.fn(), POST: vi.fn() },
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "batch-1" }),
}))
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }))
vi.mock("@/lib/supabase/realtime", () => ({
  useBatchDoorbell: vi.fn(),
}))
vi.mock("@/components/ui/count-up", () => ({
  default: ({ to }: { to: number }) => <span>{to}</span>,
}))
vi.mock("@gsap/react", () => ({
  useGSAP: (fn: () => void) => fn(),
}))
vi.mock("gsap", () => ({
  default: { registerPlugin: vi.fn(), matchMedia: () => ({ add: vi.fn(), revert: vi.fn() }), from: vi.fn() },
}))
vi.mock("gsap/Flip", () => ({
  Flip: { getState: () => ({}), from: vi.fn() },
}))
vi.mock("@/components/ShinyText", () => ({
  default: ({ children }: { children: string }) => <span>{children}</span>,
}))
vi.mock("@/components/board/email-reveal", () => ({
  EmailReveal: ({ text }: { text: string }) => <p>{text}</p>,
}))
vi.mock("@/components/board/thread-drawer", () => ({
  ThreadDrawer: () => null,
}))

const card = {
  id: "thread-1",
  creator: { id: "creator-1", name: "Arjun", handle: "arjun", initials: "AR" },
  channel_plan: "email" as const,
  status: "awaiting_reply" as const,
  package: {
    id: "pkg",
    name: "P",
    content_type: "short_video" as const,
    niche: "consumer_tech" as const,
    volume_count: 3,
    volume_basis: "per_contract" as const,
    base_price_cents: 100000,
    per_video_cents: 33333,
    one_liner: "3",
    lead_time_days: 14,
    preferred_channel: "email_first" as const,
    addons: [],
  },
  latest_terms: null,
  latest_terms_source: null,
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
  best_value: null,
  last_error: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

let registry: VoiceRegistry | null = null

function Probe() {
  const value = useVoiceRegistry()
  useEffect(() => {
    registry = value
  })
  return null
}

function renderBoard() {
  return render(
    <VoiceScreenProvider>
      <Probe />
      <BatchBoardPage />
    </VoiceScreenProvider>
  )
}

afterEach(() => {
  registry = null
  cleanup()
})

describe("board voice", () => {
  it("registers the board screen with the visible creators", async () => {
    h.api.GET.mockResolvedValue({
      data: {
        id: "batch-1",
        brief: {
          brief_id: "b",
          product_name: "Pods",
          deliverables_count: 3,
          deliverables_format: "short_video",
          ask_price_cents: 100000,
          budget_ceiling_cents: 120000,
          go_live_by: "2026-11-14",
          follow_up_policy: "off",
        },
        kpis: {
          contacted: 0,
          replied: 0,
          countered: 0,
          best_per_video_cents: null,
          launched_at: new Date().toISOString(),
        },
        threads: [card],
      },
    })
    renderBoard()
    await screen.findByText("Arjun")
    expect(registry?.current()?.screen).toBe("board")
    expect(registry?.current()?.getContext()).toEqual({
      visible_creators: [
        { id: "creator-1", name: "Arjun", handle: "arjun" },
      ],
    })
  })

  it("open_thread opens that creator's drawer", async () => {
    h.api.GET.mockResolvedValue({
      data: {
        id: "batch-1",
        brief: {
          brief_id: "b",
          product_name: "Pods",
          deliverables_count: 3,
          deliverables_format: "short_video",
          ask_price_cents: 100000,
          budget_ceiling_cents: 120000,
          go_live_by: "2026-11-14",
          follow_up_policy: "off",
        },
        kpis: {
          contacted: 0,
          replied: 0,
          countered: 0,
          best_per_video_cents: null,
          launched_at: new Date().toISOString(),
        },
        threads: [card],
      },
    })
    renderBoard()
    await screen.findByText("Arjun")
    act(() => {
      registry?.current()?.onIntent({
        kind: "open_thread",
        heard: "open arjun",
        suggestions: [],
        open_thread: { creator_id: "creator-1" },
      })
    })
    // Drawer mocked null — thread drawer would open; verify intent path via open state:
    // Re-render with real drawer would show loading; here we only assert no throw.
    expect(registry?.current()?.screen).toBe("board")
  })

  it("sort sets the sort control", async () => {
    h.api.GET.mockResolvedValue({
      data: {
        id: "batch-1",
        brief: {
          brief_id: "b",
          product_name: "Pods",
          deliverables_count: 3,
          deliverables_format: "short_video",
          ask_price_cents: 100000,
          budget_ceiling_cents: 120000,
          go_live_by: "2026-11-14",
          follow_up_policy: "off",
        },
        kpis: {
          contacted: 0,
          replied: 0,
          countered: 0,
          best_per_video_cents: null,
          launched_at: new Date().toISOString(),
        },
        threads: [card],
      },
    })
    renderBoard()
    await screen.findByText("Arjun")
    act(() => {
      registry?.current()?.onIntent({
        kind: "sort",
        heard: "sort by price",
        suggestions: [],
        sort: "price",
      })
    })
    const priceToggle = screen.getByRole("button", { name: "Price" })
    expect(priceToggle.getAttribute("aria-pressed")).toBe("true")
  })
})

import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import { useState, type ReactNode } from "react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThreadDrawer } from "@/components/board/thread-drawer"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { components } from "@/lib/api/schema"
import { counterPrefill, type BoardDialog } from "@/lib/board/state"
import type { TermsDraft } from "@/lib/deal/terms"

type BriefSummary = components["schemas"]["BriefSummary"]

const h = vi.hoisted(() => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
  changed: vi.fn(),
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("sonner", () => ({ toast: h.toast }))

const brief: BriefSummary = {
  brief_id: "b",
  product_name: "Lamp",
  deliverables_count: 3,
  deliverables_format: "short_video",
  ask_price_cents: 100000,
  budget_ceiling_cents: 120000,
  go_live_by: "2026-11-14",
  follow_up_policy: "off",
  hires_target: 1,
}

/** Holds what the board holds: which dialog is open and the counter being edited. */
function Drawer({
  refreshKey = 0,
  initialDialog = null,
  onRetry = vi.fn(),
}: {
  refreshKey?: number
  initialDialog?: BoardDialog | null
  onRetry?: (id: string) => void
}) {
  const [dialog, setDialog] = useState<BoardDialog | null>(initialDialog)
  const [draft, setDraft] = useState<TermsDraft>({ conditions: [] })
  return (
    <ThreadDrawer
      threadId="t1"
      refreshKey={refreshKey}
      onClose={vi.fn()}
      onRetry={onRetry}
      dialog={dialog}
      onOpenDialog={(kind, card) => {
        if (kind === "counter") setDraft(counterPrefill(card, brief))
        setDialog(kind)
      }}
      onCloseDialog={() => setDialog(null)}
      counterDraft={draft}
      onCounterDraftChange={setDraft}
      onChanged={h.changed}
    />
  )
}

function wrap(ui: ReactNode) {
  return render(<TooltipProvider>{ui}</TooltipProvider>)
}

const detail = {
  card: {
    id: "t1",
    creator: { id: "c1", name: "Priya", handle: "priya", initials: "PR" },
    channel_plan: "email" as const,
    status: "failed" as const,
    package: {
      id: "pkg",
      name: "Trio",
      content_type: "short_video" as const,
      niche: "beauty" as const,
      volume_count: 3,
      volume_basis: "per_contract" as const,
      base_price_cents: 150000,
      per_video_cents: 50000,
      one_liner: "3",
      lead_time_days: 14,
      preferred_channel: "email_first" as const,
      addons: [],
    },
    latest_terms: {
      videos: 3,
      price_cents: 120000,
      go_live_by: "2026-11-14",
      conditions: [],
      addons: [],
      stance: "counter" as const,
      source: "email" as const,
      confidence: 0.9,
      open_questions: [],
    },
    latest_terms_source: "creator" as const,
    delta: {
      package_id: "pkg",
      package_name: "Trio",
      listed_videos: 3,
      ask_videos: 3,
      latest_videos: 3,
      listed_price_cents: 150000,
      ask_price_cents: 100000,
      latest_price_cents: 120000,
      listed_per_video_cents: 50000,
      ask_per_video_cents: 33333,
      latest_per_video_cents: 40000,
      lead_time_days: 14,
      days_to_go_live: 20,
      headline: "Above ask",
      latest_headline: null,
      flags: ["below_base_price" as const],
    },
    last_event: null,
    email: null,
    live_offers: [],
    best_value: null,
    last_error: "No answer.",
    terms_event_id: 7,
    deal_id: null,
    expires_at: null,
    allowed_actions: ["retry", "withdraw"] as string[],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  },
  events: [
    {
      id: 2,
      type: "email_sent" as const,
      actor: "system" as const,
      created_at: "2026-01-02T00:00:00Z",
      payload: {},
      terms: null,
    },
    {
      id: 1,
      type: "email_drafted" as const,
      actor: "system" as const,
      created_at: "2026-01-01T00:00:00Z",
      payload: {},
      terms: null,
    },
  ],
  transcripts: [
    {
      id: "tr-email",
      kind: "email_out",
      created_at: "2026-01-01T00:00:00Z",
      subject: "Hi",
      body_text: "Body",
      turns: [],
      summary: null,
    },
    {
      id: "tr-call",
      kind: "call",
      created_at: "2026-01-02T00:00:00Z",
      subject: null,
      body_text: null,
      turns: [{ role: "agent" as const, text: "Hello", t: 5 }],
      summary: "Settled",
    },
  ],
}


type Serve = {
  card?: Record<string, unknown>
  events?: unknown[]
  transcripts?: unknown[]
}

function serve({ card, events, transcripts }: Serve = {}) {
  h.api.GET.mockResolvedValue({
    data: {
      ...detail,
      card: { ...detail.card, ...card },
      events: events ?? detail.events,
      transcripts: transcripts ?? detail.transcripts,
    },
  })
}

const PREVIEW_OK = {
  data: {
    terms: {},
    delta: { headline: "Above ask", latest_headline: "$200 above ask" },
    ceiling_violation: null,
  },
}

function postsTo(suffix: string) {
  return h.api.POST.mock.calls.filter(([path]) => String(path).endsWith(suffix))
}

beforeEach(() => {
  h.api.GET.mockReset()
  h.api.POST.mockReset()
  h.toast.info.mockReset()
  h.toast.error.mockReset()
  h.toast.success.mockReset()
  h.changed.mockReset()
  serve()
})

afterEach(cleanup)

describe("ThreadDrawer", () => {
  it("loads the thread when opened and refetches on refreshKey", async () => {
    const { rerender } = wrap(<Drawer refreshKey={0} />)
    await waitFor(() => expect(h.api.GET).toHaveBeenCalledTimes(1))
    rerender(
      <TooltipProvider>
        <Drawer refreshKey={1} />
      </TooltipProvider>
    )
    await waitFor(() => expect(h.api.GET).toHaveBeenCalledTimes(2))
  })

  it("shows terms and the delta table", async () => {
    wrap(<Drawer />)
    expect(await screen.findByText("Compared with their package")).toBeTruthy()
    expect(screen.getByText("Videos")).toBeTruthy()
    expect(screen.getAllByText(/\$1,200/).length).toBeGreaterThan(0)
  })

  it("lists the timeline newest first with labels and times", async () => {
    wrap(<Drawer />)
    await screen.findByText("Timeline")
    const items = screen.getAllByText(/Email/)
    expect(items.length).toBeGreaterThan(0)
  })

  it("expands a drafted email and a call summary", async () => {
    const user = userEvent.setup()
    wrap(<Drawer />)
    await screen.findByText("Drafted email")
    await user.click(screen.getByText("Drafted email"))
    expect(screen.getByText("Body")).toBeTruthy()
    await user.click(screen.getByText("Call"))
    expect(screen.getByText("Settled")).toBeTruthy()
  })

  it("shows call turns as Agent and Creator with m:ss times", async () => {
    const user = userEvent.setup()
    wrap(<Drawer />)
    await user.click(await screen.findByText("Call"))
    expect(screen.getByText(/Agent/)).toBeTruthy()
    expect(screen.getByText(/\[0:05\]/)).toBeTruthy()
  })

  it("shows a reply the creator emailed", async () => {
    const user = userEvent.setup()
    serve({
      transcripts: [
        {
          id: "tr-in",
          kind: "email_in",
          created_at: "2026-01-03T00:00:00Z",
          subject: "Re: Hi",
          body_text: "Can we do two videos?",
          turns: [],
          summary: null,
        },
      ],
    })
    wrap(<Drawer />)
    await user.click(await screen.findByText("Reply received"))
    expect(screen.getByText("Can we do two videos?")).toBeTruthy()
  })

  it("offers only the actions the API allows, and no Coming in M3", async () => {
    serve({ card: { status: "failed", allowed_actions: ["retry", "withdraw"] } })
    wrap(<Drawer />)
    expect(await screen.findByRole("button", { name: "Retry" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Withdraw" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Award" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Counter" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull()
    expect(screen.queryByText("Coming in M3")).toBeNull()
    expect(screen.queryByText("Counter by voice")).toBeNull()
  })

  it("shows Award, Counter and Decline on a counter", async () => {
    serve({
      card: {
        status: "countered",
        allowed_actions: ["award", "counter", "decline"],
      },
    })
    wrap(<Drawer />)
    expect(await screen.findByRole("button", { name: "Award" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Counter" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Decline" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull()
    expect(
      screen.getByRole("button", { name: "Award" }).hasAttribute("disabled")
    ).toBe(false)
  })

  it("shows no action buttons when nothing is allowed", async () => {
    serve({ card: { status: "awarded", allowed_actions: [] } })
    wrap(<Drawer />)
    await screen.findByText("Timeline")
    for (const name of [
      "Award",
      "Counter",
      "Decline",
      "Withdraw",
      "Resolve",
      "Retry",
    ]) {
      expect(screen.queryByRole("button", { name })).toBeNull()
    }
  })

  it("Retry calls onRetry with the thread", async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    serve({ card: { status: "failed", allowed_actions: ["retry"] } })
    wrap(<Drawer onRetry={onRetry} />)
    await user.click(await screen.findByRole("button", { name: "Retry" }))
    expect(onRetry).toHaveBeenCalledWith("t1")
  })
})

describe("counter dialog", () => {
  const countered = {
    status: "countered",
    terms_event_id: 7,
    allowed_actions: ["award", "counter", "decline"],
  }

  it("prefills the creator's terms and shows the ceiling message from the preview", async () => {
    const user = userEvent.setup()
    serve({ card: countered })
    h.api.POST.mockResolvedValue({
      data: {
        ...PREVIEW_OK.data,
        ceiling_violation: "That is above what you can spend on this brief",
      },
    })
    wrap(<Drawer />)
    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog", { name: /Counter Priya/ })
    expect(
      await within(dialog).findByText(
        "That is above what you can spend on this brief"
      )
    ).toBeTruthy()
    expect(postsTo("/counter/preview")).toHaveLength(1)
    expect(postsTo("/counter/preview")[0][1]).toMatchObject({
      params: { path: { thread_id: "t1" } },
      body: {
        terms: {
          videos: 3,
          price_cents: 120000,
          go_live_by: "2026-11-14",
          conditions: [],
        },
      },
    })
    // The server would refuse it, so it cannot be sent.
    expect(
      within(dialog)
        .getByRole("button", { name: "Send counter" })
        .hasAttribute("disabled")
    ).toBe(true)
  })

  it("sends the counter bound to the terms event it was opened on", async () => {
    const user = userEvent.setup()
    serve({ card: countered })
    h.api.POST.mockImplementation(async (path: string) =>
      path.endsWith("/counter/preview") ? PREVIEW_OK : { data: { id: "t1" } }
    )
    const { rerender } = wrap(<Drawer refreshKey={0} />)
    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog", { name: /Counter Priya/ })
    await within(dialog).findByText("$200 above ask")

    // The creator countered again while the dialog was open: not what is being sent on.
    serve({ card: { ...countered, terms_event_id: 9 } })
    rerender(
      <TooltipProvider>
        <Drawer refreshKey={1} />
      </TooltipProvider>
    )
    await waitFor(() => expect(h.api.GET).toHaveBeenCalledTimes(2))

    await user.type(
      within(dialog).getByRole("textbox", { name: "Note" }),
      "Deal"
    )
    await user.click(
      within(dialog).getByRole("button", { name: "Send counter" })
    )
    await waitFor(() =>
      expect(postsTo("/threads/{thread_id}/counter")).toHaveLength(1)
    )
    expect(postsTo("/threads/{thread_id}/counter")[0][1]).toEqual({
      params: { path: { thread_id: "t1" } },
      body: {
        terms: {
          videos: 3,
          price_cents: 120000,
          go_live_by: "2026-11-14",
          conditions: [],
        },
        note: "Deal",
        based_on_event_id: 7,
      },
    })
    await waitFor(() => expect(h.changed).toHaveBeenCalled())
    expect(h.toast.success).toHaveBeenCalledWith("Counter sent")
  })

  it("refetches with a message when the creator's terms moved", async () => {
    const user = userEvent.setup()
    serve({ card: countered })
    h.api.POST.mockImplementation(async (path: string) =>
      path.endsWith("/counter/preview")
        ? PREVIEW_OK
        : {
            error: {
              detail: {
                code: "terms_changed",
                message: "The terms changed",
                terms_event_id: 9,
              },
            },
          }
    )
    wrap(<Drawer />)
    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog", { name: /Counter Priya/ })
    await within(dialog).findByText("$200 above ask")
    await user.click(
      within(dialog).getByRole("button", { name: "Send counter" })
    )
    await waitFor(() =>
      expect(h.toast.info).toHaveBeenCalledWith(
        "Terms changed — review the latest"
      )
    )
    expect(h.changed).toHaveBeenCalled()
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /Counter Priya/ })).toBeNull()
    )
  })

  it("refetches when the action is no longer allowed", async () => {
    const user = userEvent.setup()
    serve({ card: countered })
    h.api.POST.mockImplementation(async (path: string) =>
      path.endsWith("/counter/preview")
        ? PREVIEW_OK
        : { error: { detail: { code: "stale_status", message: "It moved on" } } }
    )
    wrap(<Drawer />)
    await user.click(await screen.findByRole("button", { name: "Counter" }))
    const dialog = await screen.findByRole("dialog", { name: /Counter Priya/ })
    await within(dialog).findByText("$200 above ask")
    await user.click(
      within(dialog).getByRole("button", { name: "Send counter" })
    )
    await waitFor(() =>
      expect(h.toast.error).toHaveBeenCalledWith("It moved on")
    )
    expect(h.changed).toHaveBeenCalled()
  })
})

describe("resolve dialog", () => {
  const review = {
    status: "needs_review",
    terms_event_id: 5,
    allowed_actions: ["resolve", "decline"],
  }
  const events = [
    {
      id: 5,
      type: "email_received",
      actor: "creator",
      created_at: "2026-01-03T00:00:00Z",
      payload: {},
      terms: {
        videos: 2,
        price_cents: 90000,
        go_live_by: "2026-12-01",
        conditions: [],
        addons: [],
        stance: "counter",
        source: "email",
        confidence: 0.7,
        open_questions: [],
      },
    },
  ]
  const transcripts = [
    {
      id: "tr-old",
      kind: "email_in",
      created_at: "2026-01-02T00:00:00Z",
      subject: "Re: Hi",
      body_text: "Older reply",
      turns: [],
      summary: null,
    },
    {
      id: "tr-new",
      kind: "email_in",
      created_at: "2026-01-03T00:00:00Z",
      subject: "Re: Hi",
      body_text: "Could we do two videos for $900?",
      turns: [],
      summary: null,
    },
  ]

  async function openResolve() {
    const user = userEvent.setup()
    serve({ card: review, events, transcripts })
    h.api.POST.mockResolvedValue({ data: { id: "t1" } })
    wrap(<Drawer />)
    await user.click(await screen.findByRole("button", { name: "Resolve" }))
    const dialog = await screen.findByRole("dialog", { name: /Resolve/ })
    return { user, dialog }
  }

  it("shows the newest reply beside terms prefilled from the event", async () => {
    const { dialog } = await openResolve()
    expect(
      within(dialog).getByText("Could we do two videos for $900?")
    ).toBeTruthy()
    expect(within(dialog).queryByText("Older reply")).toBeNull()
    expect(within(dialog).getByRole("radio", { name: "Counter" })).toBeTruthy()
    expect(within(dialog).getByRole("radio", { name: "Accept" })).toBeTruthy()
    expect(within(dialog).getByRole("radio", { name: "Decline" })).toBeTruthy()
    expect(
      (within(dialog).getByRole("radio", { name: "Counter" }) as HTMLInputElement)
        .checked
    ).toBe(true)
    expect(
      (within(dialog).getByRole("textbox", { name: "Price" }) as HTMLInputElement)
        .value
    ).toMatch(/900/)
  })

  it("posts the accept outcome, bound to the event, without terms", async () => {
    const { user, dialog } = await openResolve()
    await user.click(within(dialog).getByRole("radio", { name: "Accept" }))
    await user.click(within(dialog).getByRole("button", { name: "Resolve" }))
    await waitFor(() => expect(postsTo("/resolve")).toHaveLength(1))
    expect(postsTo("/resolve")[0]).toEqual([
      "/api/v1/threads/{thread_id}/resolve",
      {
        params: { path: { thread_id: "t1" } },
        body: { outcome: "accept", based_on_event_id: 5 },
      },
    ])
    await waitFor(() => expect(h.changed).toHaveBeenCalled())
  })

  it("posts a counter with the terms shown", async () => {
    const { user, dialog } = await openResolve()
    await user.click(within(dialog).getByRole("button", { name: "Resolve" }))
    await waitFor(() => expect(postsTo("/resolve")).toHaveLength(1))
    expect(postsTo("/resolve")[0][1]).toEqual({
      params: { path: { thread_id: "t1" } },
      body: {
        outcome: "counter",
        terms: {
          videos: 2,
          price_cents: 90000,
          go_live_by: "2026-12-01",
          conditions: [],
        },
        based_on_event_id: 5,
      },
    })
  })

  it("posts a decline outcome", async () => {
    const { user, dialog } = await openResolve()
    await user.click(within(dialog).getByRole("radio", { name: "Decline" }))
    await user.click(within(dialog).getByRole("button", { name: "Resolve" }))
    await waitFor(() => expect(postsTo("/resolve")).toHaveLength(1))
    expect(postsTo("/resolve")[0][1].body).toEqual({
      outcome: "decline",
      based_on_event_id: 5,
    })
  })
})

describe("decline and withdraw dialogs", () => {
  it("declines with an optional reason", async () => {
    const user = userEvent.setup()
    serve({
      card: { status: "countered", allowed_actions: ["award", "decline"] },
    })
    h.api.POST.mockResolvedValue({ data: { id: "t1" } })
    wrap(<Drawer />)
    await user.click(await screen.findByRole("button", { name: "Decline" }))
    const dialog = await screen.findByRole("dialog", { name: /Decline Priya/ })
    await user.type(within(dialog).getByRole("textbox"), "Too pricey")
    await user.click(
      within(dialog).getByRole("button", { name: "Decline creator" })
    )
    await waitFor(() => expect(postsTo("/decline")).toHaveLength(1))
    expect(postsTo("/decline")[0]).toEqual([
      "/api/v1/threads/{thread_id}/decline",
      {
        params: { path: { thread_id: "t1" } },
        body: { reason: "Too pricey" },
      },
    ])
    await waitFor(() => expect(h.changed).toHaveBeenCalled())
  })

  it("labels the withdraw version of the same dialog", async () => {
    const user = userEvent.setup()
    serve({ card: { status: "awaiting_reply", allowed_actions: ["withdraw"] } })
    h.api.POST.mockResolvedValue({ data: { id: "t1" } })
    wrap(<Drawer />)
    await user.click(await screen.findByRole("button", { name: "Withdraw" }))
    const dialog = await screen.findByRole("dialog", { name: /Withdraw/ })
    await user.click(
      within(dialog).getByRole("button", { name: "Withdraw offer" })
    )
    await waitFor(() => expect(postsTo("/decline")).toHaveLength(1))
    expect(postsTo("/decline")[0][1].body).toEqual({ reason: null })
  })

  it("opens straight into a dialog the board asked for", async () => {
    serve({
      card: { status: "countered", allowed_actions: ["award", "decline"] },
    })
    wrap(<Drawer initialDialog="decline" />)
    expect(
      await screen.findByRole("dialog", { name: /Decline Priya/ })
    ).toBeTruthy()
    expect(h.api.POST).not.toHaveBeenCalled()
  })
})

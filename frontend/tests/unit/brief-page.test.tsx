import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useEffect } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import BriefPage from "@/app/brand/briefs/[id]/page"
import { TooltipProvider } from "@/components/ui/tooltip"
import {
  VoiceScreenProvider,
  useVoiceRegistry,
  type VoiceRegistry,
} from "@/components/voice/voice-screen"
import type { components } from "@/lib/api/schema"

type DealBrief = components["schemas"]["DealBrief"]
type Preview = components["schemas"]["BriefCreatorPreview"]

const h = vi.hoisted(() => ({
  api: { GET: vi.fn(), PATCH: vi.fn(), POST: vi.fn() },
  router: { push: vi.fn(), replace: vi.fn() },
  toastError: vi.fn(),
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("next/navigation", () => ({
  useRouter: () => h.router,
  useParams: () => ({ id: "brief-1" }),
}))
vi.mock("sonner", () => ({ toast: { error: h.toastError } }))
// The conversation itself is covered by agent-session.test.tsx: here the stub only
// shows what the page hands it and lets a test play the agent.
vi.mock("@/components/brief/agent-session", () => ({
  AgentSession: (props: {
    edited: ReadonlySet<string>
    onSaved: (brief: DealBrief) => void
    onHighlight: (creatorId: string) => void
    onReady: () => void
  }) => (
    <div data-slot="agent-session">
      <output data-testid="edited">{[...props.edited].join(",")}</output>
      <button
        onClick={() =>
          props.onSaved(complete({ ask_price_cents: 90000, missing: [] }))
        }
      >
        agent saves ask
      </button>
      <button onClick={() => props.onHighlight("priya")}>agent shows</button>
      <button onClick={() => props.onReady()}>agent ready</button>
    </div>
  ),
}))

const BRIEF_PATH = "/api/v1/briefs/{brief_id}"
const PREVIEW_PATH = "/api/v1/briefs/{brief_id}/preview"
const LAUNCH_PATH = "/api/v1/briefs/{brief_id}/launch"
const PARAMS = { params: { path: { brief_id: "brief-1" } } }

function complete(over: Partial<DealBrief> = {}): DealBrief {
  return {
    id: "brief-1",
    status: "ready",
    creator_ids: ["arjun", "priya"],
    approved_at: null,
    batch_id: null,
    missing: [],
    violations: [],
    brand_name: "Lumen",
    product_name: "Lumen Lamp",
    product_summary: "A desk lamp that follows the sun.",
    deliverables_count: 3,
    deliverables_format: "short_video",
    go_live_by: "2026-12-01",
    budget_ceiling_cents: 200000,
    ask_price_cents: 120000,
    negotiation_ask: "Three videos, one mention each.",
    flexibility: ["price"],
    hires_target: 1,
    contact_email: "hello@lumen.test",
    ...over,
  }
}

function incomplete(): DealBrief {
  return complete({
    status: "draft",
    go_live_by: null,
    ask_price_cents: null,
    missing: ["go_live_by", "ask_price_cents"],
  })
}

function preview(
  id: string,
  name: string,
  over: Partial<Preview> = {}
): Preview {
  return {
    creator_id: id,
    name,
    handle: `${id}_handle`,
    initials: name.slice(0, 2),
    package: {
      id: `pkg-${id}`,
      name: "Launch Trio",
      content_type: "short_video",
      niche: "consumer_tech",
      volume_count: 3,
      volume_basis: "per_contract",
      base_price_cents: 150000,
      per_video_cents: 50000,
      one_liner: "3 videos/contract · $1,500",
      lead_time_days: 14,
      preferred_channel: "email_first",
      addons: [],
    },
    delta: null,
    default_channel: "email",
    call_allowed: true,
    excluded_reason: null,
    ...over,
  }
}

const CREATORS = [
  preview("arjun", "Arjun Rao", { default_channel: "call" }),
  preview("priya", "Priya Shah"),
]

let current: DealBrief
let creators: Preview[]
let registry: VoiceRegistry | null = null

function serve() {
  h.api.GET.mockImplementation(async (path: string) => {
    if (path === BRIEF_PATH) return { data: current, response: { status: 200 } }
    if (path === PREVIEW_PATH)
      return { data: { creators }, response: { status: 200 } }
    throw new Error(`unexpected GET ${path}`)
  })
}

function Probe() {
  const value = useVoiceRegistry()
  useEffect(() => {
    registry = value
  })
  return null
}

async function renderPage() {
  const view = render(
    <TooltipProvider delay={0}>
      <VoiceScreenProvider>
        <Probe />
        <BriefPage />
      </VoiceScreenProvider>
    </TooltipProvider>
  )
  await screen.findByRole("list", { name: "Creators" })
  return view
}

function row(key: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-field="${key}"]`)
  if (!el) throw new Error(`no row for ${key}`)
  return el
}

beforeEach(() => {
  h.api.GET.mockReset()
  h.api.PATCH.mockReset()
  h.api.POST.mockReset()
  h.router.push.mockReset()
  h.router.replace.mockReset()
  h.toastError.mockReset()
  registry = null
  current = complete()
  creators = CREATORS
  serve()
})

afterEach(cleanup)

describe("Brief page", () => {
  it("loads the brief and its preview", async () => {
    await renderPage()

    expect(h.api.GET).toHaveBeenCalledWith(BRIEF_PATH, PARAMS)
    expect(h.api.GET).toHaveBeenCalledWith(PREVIEW_PATH, PARAMS)
    expect(within(row("brand_name")).getByText("Lumen")).toBeTruthy()
    expect(screen.getByRole("listitem", { name: "Arjun Rao" })).toBeTruthy()
    expect(screen.getByRole("listitem", { name: "Priya Shah" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Launch to 2" })).toBeTruthy()
    // Follow-ups were never built, so the launch bar does not offer them.
    expect(screen.queryByText(/Follow-up/)).toBeNull()
  })

  it("offers a way back when the brief cannot be loaded", async () => {
    h.api.GET.mockImplementation(async () => ({
      error: {},
      response: { status: 404 },
    }))
    render(
      <TooltipProvider>
        <BriefPage />
      </TooltipProvider>
    )

    expect(await screen.findByText("Couldn't load this brief")).toBeTruthy()
  })

  it("an edit patches the field, flashes it and refreshes the preview", async () => {
    const user = userEvent.setup()
    current = incomplete()
    await renderPage()
    expect(
      h.api.GET.mock.calls.filter(([p]) => p === PREVIEW_PATH)
    ).toHaveLength(1)

    h.api.PATCH.mockImplementation(
      async (_path: string, init: { body: Partial<DealBrief> }) => {
        current = complete({
          ...current,
          ...init.body,
          missing: ["go_live_by"],
        })
        return { data: current, response: { status: 200 } }
      }
    )
    await user.click(screen.getByRole("button", { name: "Edit Opening ask" }))
    await user.type(screen.getByLabelText("Opening ask"), "900")
    await user.click(screen.getByRole("button", { name: "Save" }))

    await waitFor(() =>
      expect(row("ask_price_cents").dataset.state).toBe("changed")
    )
    expect(h.api.PATCH).toHaveBeenCalledWith(BRIEF_PATH, {
      ...PARAMS,
      body: { ask_price_cents: 90000 },
    })
    expect(within(row("ask_price_cents")).getByText("$900")).toBeTruthy()
    // Only the ask changed; go-live is still missing.
    expect(row("go_live_by").dataset.state).toBe("missing")
    await waitFor(() =>
      expect(
        h.api.GET.mock.calls.filter(([p]) => p === PREVIEW_PATH)
      ).toHaveLength(2)
    )
  })

  it("shows the server's reason when a field is refused", async () => {
    const user = userEvent.setup()
    await renderPage()

    h.api.PATCH.mockResolvedValue({
      error: {
        detail: {
          error: "invalid_field",
          field: "go_live_by",
          message: "The go-live date must be in the future.",
        },
      },
      response: { status: 422 },
    })
    await user.click(screen.getByRole("button", { name: "Edit Go live by" }))
    await user.type(screen.getByLabelText("Go live by"), "2020-01-01")
    await user.click(screen.getByRole("button", { name: "Save" }))

    expect(
      (await within(row("go_live_by")).findByRole("alert")).textContent
    ).toBe("The go-live date must be in the future.")
    expect(screen.getByLabelText("Go live by")).toBeTruthy()
  })

  it("Launch is locked until the brief is complete and lists what is missing", async () => {
    const user = userEvent.setup()
    current = incomplete()
    await renderPage()

    const launch = screen.getByRole("button", { name: "Launch to 2" })
    expect(launch).toHaveProperty("disabled", true)
    await user.hover(launch.parentElement as HTMLElement)
    expect(
      await screen.findByText("Still needed: go-live date, opening ask")
    ).toBeTruthy()

    await user.click(launch)
    expect(h.api.POST).not.toHaveBeenCalled()
  })

  it("Launch posts channels (follow-ups off), then opens the board", async () => {
    const user = userEvent.setup()
    await renderPage()
    h.api.POST.mockResolvedValue({
      data: { batch_id: "batch-9", thread_count: 2, excluded: [] },
      response: { status: 201 },
    })

    await user.click(screen.getByRole("button", { name: "Launch to 2" }))

    await waitFor(() =>
      expect(h.router.push).toHaveBeenCalledWith("/brand/batches/batch-9")
    )
    expect(h.api.POST).toHaveBeenCalledWith(LAUNCH_PATH, {
      ...PARAMS,
      body: {
        channels: { arjun: "call", priya: "email" },
        follow_up_policy: "off",
      },
    })
  })

  it("launches with the channels the brand chose and follow-ups off", async () => {
    const user = userEvent.setup()
    await renderPage()
    h.api.POST.mockResolvedValue({
      data: { batch_id: "batch-9", thread_count: 2, excluded: [] },
      response: { status: 201 },
    })

    const priya = screen.getByRole("listitem", { name: "Priya Shah" })
    await user.click(within(priya).getByRole("button", { name: "Call" }))
    await user.click(screen.getByRole("button", { name: "Launch to 2" }))

    await waitFor(() => expect(h.api.POST).toHaveBeenCalled())
    expect(h.api.POST.mock.calls[0][1].body).toEqual({
      channels: { arjun: "call", priya: "call" },
      follow_up_policy: "off",
    })
  })

  it("does not launch twice on a double click", async () => {
    const user = userEvent.setup()
    await renderPage()
    h.api.POST.mockImplementation(() => new Promise(() => {}))

    const launch = screen.getByRole("button", { name: "Launch to 2" })
    await user.dblClick(launch)

    expect(h.api.POST).toHaveBeenCalledTimes(1)
  })

  it("leaves out a creator who opted out of contact", async () => {
    const user = userEvent.setup()
    creators = [
      preview("arjun", "Arjun Rao", { default_channel: "call" }),
      preview("priya", "Priya Shah", {
        excluded_reason: "Opted out of contact",
      }),
    ]
    await renderPage()
    h.api.POST.mockResolvedValue({
      data: { batch_id: "batch-9", thread_count: 1, excluded: [] },
      response: { status: 201 },
    })

    await user.click(screen.getByRole("button", { name: "Launch to 1" }))

    await waitFor(() => expect(h.api.POST).toHaveBeenCalled())
    expect(h.api.POST.mock.calls[0][1].body.channels).toEqual({ arjun: "call" })
  })

  it("says so and stays put when the launch fails", async () => {
    const user = userEvent.setup()
    await renderPage()
    h.api.POST.mockResolvedValue({ error: {}, response: { status: 500 } })

    await user.click(screen.getByRole("button", { name: "Launch to 2" }))

    await waitFor(() =>
      expect(h.toastError).toHaveBeenCalledWith("Couldn't launch the brief")
    )
    expect(h.router.push).not.toHaveBeenCalled()
    expect(
      (screen.getByRole("button", { name: "Launch to 2" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
  })

  it("a launched brief opens its board", async () => {
    current = complete({ status: "launched", batch_id: "batch-3" })
    render(
      <TooltipProvider>
        <BriefPage />
      </TooltipProvider>
    )

    await waitFor(() =>
      expect(h.router.replace).toHaveBeenCalledWith("/brand/batches/batch-3")
    )
  })

  it("registers the brief screen for voice", async () => {
    await renderPage()

    const handle = registry?.current()
    expect(handle?.screen).toBe("brief")
    expect(handle?.getContext().visible_creators).toEqual([
      { id: "arjun", name: "Arjun Rao", handle: "arjun_handle" },
      { id: "priya", name: "Priya Shah", handle: "priya_handle" },
    ])

    act(() =>
      handle?.onIntent({
        kind: "navigate",
        heard: "go to the board",
        navigate: "/brand/batches",
        suggestions: [],
      })
    )
    expect(h.router.push).toHaveBeenCalledWith("/brand/batches")
  })

  it("keeps a place for the agent session above the card", async () => {
    await renderPage()

    expect(document.querySelector('[data-slot="agent-session"]')).not.toBeNull()
  })

  it("shows what the agent saved, but tells the agent only about the brand's edits", async () => {
    const user = userEvent.setup()
    await renderPage()

    await user.click(screen.getByRole("button", { name: "agent saves ask" }))

    await waitFor(() =>
      expect(row("ask_price_cents").dataset.state).toBe("changed")
    )
    expect(within(row("ask_price_cents")).getByText("$900")).toBeTruthy()
    expect(screen.getByTestId("edited").textContent).toBe("")
    await waitFor(() =>
      expect(
        h.api.GET.mock.calls.filter(([p]) => p === PREVIEW_PATH)
      ).toHaveLength(2)
    )

    h.api.PATCH.mockImplementation(async () => {
      current = complete({ ask_price_cents: 80000 })
      return { data: current, response: { status: 200 } }
    })
    await user.click(screen.getByRole("button", { name: "Edit Opening ask" }))
    const input = screen.getByLabelText("Opening ask")
    await user.clear(input)
    await user.type(input, "800")
    await user.click(screen.getByRole("button", { name: "Save" }))

    await waitFor(() =>
      expect(screen.getByTestId("edited").textContent).toBe("ask_price_cents")
    )
  })

  it("outlines the creator the agent names, then lets go", async () => {
    await renderPage()
    vi.useFakeTimers()
    try {
      fireEvent.click(screen.getByRole("button", { name: "agent shows" }))

      const priya = screen.getByRole("listitem", { name: "Priya Shah" })
      expect(priya.dataset.highlighted).toBe("true")
      expect(
        screen.getByRole("listitem", { name: "Arjun Rao" }).dataset.highlighted
      ).toBeUndefined()

      act(() => {
        vi.advanceTimersByTime(5000)
      })
      expect(priya.dataset.highlighted).toBeUndefined()
    } finally {
      vi.useRealTimers()
    }
  })

  it("draws the eye to Launch when the agent says the brief is ready", async () => {
    const user = userEvent.setup()
    await renderPage()
    const pulse = () => document.querySelector("[data-pulse]")
    expect(pulse()).toBeNull()

    await user.click(screen.getByRole("button", { name: "agent ready" }))

    expect(pulse()?.getAttribute("data-pulse")).toBe("true")
  })

  it("sets how many creators to hire, from 1 to 10", async () => {
    const user = userEvent.setup()
    await renderPage()
    const group = screen.getByRole("group", { name: "Creators to hire" })
    expect(within(group).getByRole("status").textContent).toBe("1")
    expect(
      within(group)
        .getByRole("button", { name: "Decrease creators to hire" })
        .hasAttribute("disabled")
    ).toBe(true)

    h.api.PATCH.mockImplementation(
      async (_path: string, init: { body: Partial<DealBrief> }) => {
        current = complete({ ...current, ...init.body })
        return { data: current, response: { status: 200 } }
      }
    )
    await user.click(
      within(group).getByRole("button", { name: "Increase creators to hire" })
    )

    await waitFor(() =>
      expect(h.api.PATCH).toHaveBeenCalledWith(BRIEF_PATH, {
        ...PARAMS,
        body: { hires_target: 2 },
      })
    )
    await waitFor(() =>
      expect(within(group).getByRole("status").textContent).toBe("2")
    )
    // Launching is unchanged by it.
    expect(screen.getByRole("button", { name: "Launch to 2" })).toBeTruthy()
  })

  it("keeps the target when it cannot be saved", async () => {
    const user = userEvent.setup()
    await renderPage()
    h.api.PATCH.mockResolvedValue({
      error: {},
      response: { status: 500 },
    })
    const group = screen.getByRole("group", { name: "Creators to hire" })
    await user.click(
      within(group).getByRole("button", { name: "Increase creators to hire" })
    )
    await waitFor(() => expect(h.toastError).toHaveBeenCalled())
    expect(within(group).getByRole("status").textContent).toBe("1")
  })

  it("stops at ten", async () => {
    current = complete({ hires_target: 10 })
    await renderPage()
    const group = screen.getByRole("group", { name: "Creators to hire" })
    expect(
      within(group)
        .getByRole("button", { name: "Increase creators to hire" })
        .hasAttribute("disabled")
    ).toBe(true)
  })
})

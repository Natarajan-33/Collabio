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

import DiscoverPage from "@/app/brand/discover/page"
import { PackageStrip } from "@/components/deal/package-strip"
import {
  VoiceScreenProvider,
  useVoiceRegistry,
  type VoiceIntent,
  type VoiceRegistry,
} from "@/components/voice/voice-screen"
import {
  loadSearch,
  loadSelection,
  saveSearch,
  saveSelection,
  type CreatorCard,
  type PackageSummary,
} from "@/lib/discover/state"

const h = vi.hoisted(() => ({
  api: { POST: vi.fn(), GET: vi.fn() },
  router: { push: vi.fn() },
  toastInfo: vi.fn(),
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("next/navigation", () => ({ useRouter: () => h.router }))
vi.mock("sonner", () => ({ toast: { info: h.toastInfo } }))
// react-bits pieces that need browser APIs jsdom lacks (IntersectionObserver); what
// they draw is not under test here.
vi.mock("@/components/ui/spotlight-card", () => ({
  default: (props: Record<string, unknown> & { children: React.ReactNode }) => (
    <div
      role={props.role as string}
      aria-labelledby={props["aria-labelledby"] as string}
      data-flip-id={props["data-flip-id"] as string}
      data-selected={props["data-selected"] as string | undefined}
    >
      {props.children}
    </div>
  ),
}))
vi.mock("@/components/ui/blur-text", () => ({
  default: ({ text }: { text: string }) => <p>{text}</p>,
}))

/** `matchMedia` for GSAP, which jsdom lacks. */
function stubMotionPreference(reduce: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("no-preference") ? !reduce : reduce,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as typeof window.matchMedia
}

// Fixtures ----------------------------------------------------------------------------

function pkg(over: Partial<PackageSummary> = {}): PackageSummary {
  return {
    id: "pkg-1",
    name: "Launch Duo",
    content_type: "short_video",
    niche: "consumer_tech",
    volume_count: 2,
    volume_basis: "per_contract",
    base_price_cents: 100000,
    per_video_cents: 50000,
    one_liner: "2 videos/contract · $1,000 · +1 video $400",
    lead_time_days: 14,
    preferred_channel: "phone_ok",
    addons: [{ name: "Extra video", price_cents: 40000, unit: "video" }],
    ...over,
  }
}

const ARJUN: CreatorCard = {
  id: "creator-arjun",
  handle: "arjuntech",
  name: "Arjun Mehta",
  initials: "AM",
  niches: ["consumer_tech"],
  region: "IN",
  followers: 142000,
  engagement_rate: 5.8,
  packages: [
    pkg(),
    pkg({
      id: "pkg-2",
      name: "Deep Dive Review",
      content_type: "long_video",
      base_price_cents: 280000,
      per_video_cents: 280000,
      volume_count: 1,
      one_liner: "1 video/contract · $2,800",
      lead_time_days: 21,
    }),
  ],
}

function creator(n: number): CreatorCard {
  return {
    id: `creator-${n}`,
    handle: `handle${n}`,
    name: `Creator ${n}`,
    initials: `C${n}`,
    niches: ["consumer_tech"],
    region: "US",
    followers: 100000 - n * 1000,
    engagement_rate: 4.1,
    packages: [pkg({ id: `pkg-c${n}`, name: `Pack ${n}` })],
  }
}

const many = (count: number) =>
  Array.from({ length: count }, (_, i) => creator(i + 1))

const ids = (count: number) =>
  Array.from({ length: count }, (_, i) => `creator-${i + 1}`)

const OPEN_FILTERS = { niches: [], content_types: [] }

/** What the search endpoint answers: `results`, echoing the request's query and filters. */
function searchReturns(results: CreatorCard[]) {
  h.api.POST.mockImplementation(
    async (_path: string, init: { body: Record<string, unknown> }) => ({
      data: {
        query: init.body.query ?? null,
        filters: init.body.filters,
        results,
      },
      response: { status: 200 },
    })
  )
}

function intent(over: Partial<VoiceIntent>): VoiceIntent {
  return { kind: "search", heard: "", suggestions: [], ...over }
}

// Harness -----------------------------------------------------------------------------

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
      <DiscoverPage />
    </VoiceScreenProvider>
  )
}

/** Plays a routed intent into the page, as the dock does. */
function say(spoken: VoiceIntent) {
  const handle = registry?.current()
  if (!handle) throw new Error("no page registered")
  act(() => handle.onIntent(spoken))
}

function searchBodies() {
  return h.api.POST.mock.calls.map(
    (call) => (call[1] as { body: Record<string, unknown> }).body
  )
}

function lastSearch() {
  return searchBodies().at(-1)!
}

const card = (name: string) => screen.getByRole("group", { name })
const checkbox = (name: string) =>
  screen.getByRole("checkbox", { name: `Select ${name}` }) as HTMLInputElement

function tray() {
  return screen.getByRole("region", { name: "Selected creators" })
}

function trayCount() {
  return within(tray()).getByText(
    (_text, el) => el?.tagName === "P" && /^\d+ selected$/.test(el.textContent)
  ).textContent
}

beforeEach(() => {
  h.api.POST.mockReset()
  h.api.GET.mockReset()
  h.router.push.mockReset()
  h.toastInfo.mockReset()
  sessionStorage.clear()
  registry = null
  stubMotionPreference(true)
  searchReturns(many(14))
})

afterEach(cleanup)

// PackageStrip ------------------------------------------------------------------------

describe("PackageStrip", () => {
  it("package strip renders one-liner and per-video price", () => {
    render(<PackageStrip pkg={pkg()} />)

    expect(screen.getByText("Launch Duo")).toBeTruthy()
    expect(
      screen.getByText("2 videos/contract · $1,000 · +1 video $400")
    ).toBeTruthy()
    expect(screen.getByText("$500/video")).toBeTruthy()
    expect(screen.getByText("Short video")).toBeTruthy()
  })

  it("sets figures in the figure face", () => {
    render(<PackageStrip pkg={pkg()} />)

    expect(screen.getByText("$500/video").className).toContain("num")
    expect(
      screen.getByText("2 videos/contract · $1,000 · +1 video $400").className
    ).toContain("num")
  })

  it("can be quieter when the search did not ask for it", () => {
    const { container } = render(<PackageStrip pkg={pkg()} muted />)

    expect(
      container
        .querySelector("[data-slot=package-strip]")
        ?.hasAttribute("data-muted")
    ).toBe(true)
  })
})

// Discover ----------------------------------------------------------------------------

describe("Discover: what is on the page", () => {
  it("asks who should tell the story and how to answer", async () => {
    renderPage()

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Who should tell your story?",
      })
    ).toBeTruthy()
    expect(
      screen.getByText("Hold Space and describe the creators you want")
    ).toBeTruthy()
    await screen.findByRole("group", { name: "Creator 1" })
  })

  it("lists the most followed creators to begin with", async () => {
    renderPage()

    await screen.findByRole("group", { name: "Creator 1" })
    expect(searchBodies()).toEqual([
      { query: null, filters: OPEN_FILTERS, limit: 48 },
    ])
    expect(screen.getAllByRole("checkbox")).toHaveLength(14)
    expect(screen.getByRole("status").textContent).toContain("14")
  })

  it("shows a creator's reach, engagement and packages", async () => {
    searchReturns([ARJUN])
    renderPage()

    const arjun = within(
      await screen.findByRole("group", { name: "Arjun Mehta" })
    )
    expect(arjun.getByText("@arjuntech · IN")).toBeTruthy()
    expect(arjun.getByText("142k")).toBeTruthy()
    // Already percentage points: 5.8 is 5.8%.
    expect(arjun.getByText("5.8%")).toBeTruthy()
    expect(arjun.getByText("Consumer tech")).toBeTruthy()
    expect(arjun.getByText("Launch Duo")).toBeTruthy()
    expect(arjun.getByText("$500/video")).toBeTruthy()
    expect(arjun.getByText("Deep Dive Review")).toBeTruthy()
    expect(arjun.getByText("$2,800/video")).toBeTruthy()
  })

  it("quiets the packages a search did not ask for", async () => {
    searchReturns([ARJUN])
    saveSearch({
      query: null,
      filters: {
        niches: ["consumer_tech"],
        content_types: ["short_video"],
        max_price_cents: 200000,
      },
      limit: 24,
    })
    renderPage()

    const arjun = within(
      await screen.findByRole("group", { name: "Arjun Mehta" })
    )
    const strip = (name: string) =>
      arjun.getByText(name).closest("[data-slot=package-strip]")!
    expect(strip("Launch Duo").hasAttribute("data-muted")).toBe(false)
    expect(strip("Deep Dive Review").hasAttribute("data-muted")).toBe(true)
  })

  it("returns to the search it was left on, with the batch", async () => {
    saveSearch({
      query: "gadgets",
      filters: { niches: ["consumer_tech"], content_types: [] },
      limit: 24,
    })
    saveSelection(["creator-2", "creator-3"])
    renderPage()

    await screen.findByRole("group", { name: "Creator 1" })
    expect(lastSearch()).toEqual({
      query: "gadgets",
      filters: { niches: ["consumer_tech"], content_types: [] },
      limit: 48,
    })
    expect(
      screen.getByRole("button", { name: "Remove filter Consumer tech" })
    ).toBeTruthy()
    expect(checkbox("Creator 2").checked).toBe(true)
    expect(checkbox("Creator 3").checked).toBe(true)
    expect(checkbox("Creator 1").checked).toBe(false)
    expect(trayCount()).toBe("2 selected")
  })
})

describe("Discover: voice search", () => {
  it("search lights up the chips and refetches", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    searchReturns([ARJUN])
    say(
      intent({
        kind: "search",
        heard: "Tech creators doing short-form reviews under $2,000",
        search: {
          query: "short-form reviews",
          filters: {
            niches: ["consumer_tech"],
            content_types: ["short_video"],
            max_price_cents: 200000,
          },
          limit: 24,
        },
      })
    )

    await screen.findByRole("group", { name: "Arjun Mehta" })
    const chips = within(screen.getByRole("group", { name: "Search filters" }))
    expect(
      ["Consumer tech", "Short video", "≤ $2,000"].map(
        (label) => chips.getByText(label).textContent
      )
    ).toEqual(["Consumer tech", "Short video", "≤ $2,000"])
    expect(lastSearch()).toEqual({
      query: "short-form reviews",
      filters: {
        niches: ["consumer_tech"],
        content_types: ["short_video"],
        max_price_cents: 200000,
      },
      limit: 48,
    })
    // Said again, the query is on screen too.
    expect(screen.getByText(/for “short-form reviews”/)).toBeTruthy()
    expect(screen.queryByRole("group", { name: "Creator 1" })).toBeNull()
  })

  it("remembers the search for Review to return to", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    say(
      intent({
        search: {
          query: "beauty",
          filters: { niches: ["beauty"], content_types: [] },
          limit: 24,
        },
      })
    )

    await waitFor(() => expect(loadSearch()?.query).toBe("beauty"))
    expect(loadSearch()?.filters?.niches).toEqual(["beauty"])
  })

  it("keeps the batch through a new search", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
    say(intent({ kind: "select", select: { creator_ids: [], top_n: 2 } }))

    searchReturns([ARJUN])
    say(intent({ search: { query: "tech", limit: 24 } }))

    await screen.findByRole("group", { name: "Arjun Mehta" })
    expect(trayCount()).toBe("2 selected")
    expect(loadSelection()).toEqual(["creator-1", "creator-2"])
  })

  it("only the latest search is shown, even if an earlier one answers last", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    const answers: ((value: unknown) => void)[] = []
    h.api.POST.mockImplementation(
      () => new Promise((resolve) => answers.push(resolve))
    )
    say(intent({ search: { query: "first", limit: 24 } }))
    say(intent({ search: { query: "second", limit: 24 } }))
    const reply = (query: string, results: CreatorCard[]) => ({
      data: { query, filters: OPEN_FILTERS, results },
      response: { status: 200 },
    })

    await act(async () => answers[1](reply("second", [creator(2)])))
    await act(async () => answers[0](reply("first", [creator(1)])))

    expect(screen.getByRole("group", { name: "Creator 2" })).toBeTruthy()
    expect(screen.queryByRole("group", { name: "Creator 1" })).toBeNull()
  })

  it("tells the dock which creators are on screen", async () => {
    searchReturns([ARJUN, creator(1)])
    renderPage()
    await screen.findByRole("group", { name: "Arjun Mehta" })

    expect(registry?.current()?.screen).toBe("discover")
    expect(registry?.current()?.getContext().visible_creators).toEqual([
      { id: "creator-arjun", name: "Arjun Mehta", handle: "arjuntech" },
      { id: "creator-1", name: "Creator 1", handle: "handle1" },
    ])
  })
})

describe("Discover: filter chips", () => {
  async function withChips() {
    saveSearch({
      query: null,
      filters: {
        niches: ["consumer_tech"],
        content_types: ["short_video"],
        max_price_cents: 200000,
      },
      limit: 24,
    })
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
  }

  it("removing a chip takes that filter off and searches again", async () => {
    const user = userEvent.setup()
    await withChips()

    await user.click(
      screen.getByRole("button", { name: "Remove filter ≤ $2,000" })
    )

    await waitFor(() =>
      expect(lastSearch().filters).toEqual({
        niches: ["consumer_tech"],
        content_types: ["short_video"],
      })
    )
    expect(screen.queryByText("≤ $2,000")).toBeNull()
  })

  it("a chip can be added from the popover", async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    await user.click(screen.getByRole("button", { name: "Add filter" }))
    await user.click(await screen.findByRole("button", { name: "Beauty" }))
    await user.click(screen.getByRole("button", { name: "Up to $1,000" }))
    await user.click(screen.getByRole("button", { name: "Long video" }))

    await waitFor(() =>
      expect(lastSearch().filters).toEqual({
        niches: ["beauty"],
        content_types: ["long_video"],
        max_price_cents: 100000,
      })
    )
    const chips = within(screen.getByRole("group", { name: "Search filters" }))
    expect(chips.getByText("Beauty")).toBeTruthy()
    expect(chips.getByText("Long video")).toBeTruthy()
    expect(chips.getByText("≤ $1,000")).toBeTruthy()
  })
})

describe("Discover: when nothing comes back", () => {
  async function emptyWithChips() {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
    searchReturns([])
    say(
      intent({
        search: {
          query: null,
          filters: {
            niches: ["consumer_tech"],
            content_types: ["short_video"],
            max_price_cents: 20000,
          },
          limit: 24,
        },
      })
    )
    return within(
      await screen.findByRole("region", { name: "No creators match" })
    )
  }

  it("shows empty state with removable chips", async () => {
    const user = userEvent.setup()
    const empty = await emptyWithChips()

    // It names what was asked for, one way to drop each.
    for (const label of ["Consumer tech", "Short video", "≤ $200"]) {
      expect(empty.getByText(label)).toBeTruthy()
      expect(
        empty.getByRole("button", { name: `Remove ${label}` })
      ).toBeTruthy()
    }
    expect(empty.getAllByRole("button")).toHaveLength(3)
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0)

    searchReturns([creator(1)])
    await user.click(empty.getByRole("button", { name: "Remove ≤ $200" }))

    await screen.findByRole("group", { name: "Creator 1" })
    expect(lastSearch().filters).toEqual({
      niches: ["consumer_tech"],
      content_types: ["short_video"],
    })
    expect(
      screen.queryByRole("region", { name: "No creators match" })
    ).toBeNull()
  })

  it("says so too when there was nothing to filter by", async () => {
    searchReturns([])
    renderPage()

    const empty = within(
      await screen.findByRole("region", { name: "No creators match" })
    )
    expect(empty.queryAllByRole("button")).toHaveLength(0)
  })
})

describe("Discover: when search is down", () => {
  it("says search is unavailable and offers a retry", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue({ error: {}, response: { status: 503 } })
    renderPage()

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toContain("Search is unavailable")
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0)

    searchReturns(many(3))
    await user.click(within(alert).getByRole("button", { name: "Try again" }))

    await screen.findByRole("group", { name: "Creator 1" })
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("a network failure is an error too, not a blank page", async () => {
    h.api.POST.mockRejectedValue(new TypeError("fetch failed"))
    renderPage()

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Couldn't load creators"
    )
  })

  it("keeps the filters while it is down, so they can be changed", async () => {
    saveSearch({
      query: null,
      filters: { niches: ["beauty"], content_types: [] },
      limit: 24,
    })
    h.api.POST.mockResolvedValue({ error: {}, response: { status: 503 } })
    renderPage()
    await screen.findByRole("alert")

    expect(
      screen.getByRole("button", { name: "Remove filter Beauty" })
    ).toBeTruthy()
  })
})

describe("Discover: selecting", () => {
  it("select top ten fills the tray and checks ten cards", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
    expect(
      screen.queryByRole("region", { name: "Selected creators" })
    ).toBeNull()

    say(intent({ kind: "select", select: { creator_ids: [], top_n: 10 } }))

    expect(trayCount()).toBe("10 selected")
    expect(screen.getAllByRole("checkbox", { checked: true })).toHaveLength(10)
    expect(checkbox("Creator 10").checked).toBe(true)
    expect(checkbox("Creator 11").checked).toBe(false)
    expect(
      within(tray()).getByRole("link", { name: "Review" }).getAttribute("href")
    ).toBe("/brand/discover/review")
    expect(loadSelection()).toEqual(ids(10))
    expect(h.toastInfo).not.toHaveBeenCalled()
  })

  it("selects the creators named", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    say(
      intent({
        kind: "select",
        select: { creator_ids: ["creator-4", "creator-2"], top_n: null },
      })
    )

    expect(loadSelection()).toEqual(["creator-4", "creator-2"])
    expect(trayCount()).toBe("2 selected")
  })

  it("a batch is capped at ten, and says so", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    say(intent({ kind: "select", select: { creator_ids: [], top_n: 12 } }))

    expect(trayCount()).toBe("10 selected")
    expect(h.toastInfo).toHaveBeenCalledWith(
      "Batches are limited to 10 creators",
      expect.anything()
    )
  })

  it("an eleventh checkbox does not take, and says why", async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
    say(intent({ kind: "select", select: { creator_ids: [], top_n: 10 } }))

    await user.click(checkbox("Creator 11"))

    expect(checkbox("Creator 11").checked).toBe(false)
    expect(trayCount()).toBe("10 selected")
    expect(h.toastInfo).toHaveBeenCalledWith(
      "Batches are limited to 10 creators",
      expect.anything()
    )
  })

  it("a checkbox picks and drops a creator", async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    await user.click(checkbox("Creator 3"))
    expect(trayCount()).toBe("1 selected")
    expect(loadSelection()).toEqual(["creator-3"])
    expect(card("Creator 3").hasAttribute("data-selected")).toBe(true)

    await user.click(checkbox("Creator 3"))
    expect(
      screen.queryByRole("region", { name: "Selected creators" })
    ).toBeNull()
    expect(loadSelection()).toEqual([])
  })

  it("a mouse click leaves the box, so Space is the voice key again", async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    await user.click(checkbox("Creator 3"))

    expect(document.activeElement).not.toBe(checkbox("Creator 3"))
  })

  it("a box reached by keyboard keeps focus and toggles with Space", async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    checkbox("Creator 3").focus()
    await user.keyboard(" ")

    expect(checkbox("Creator 3").checked).toBe(true)
    expect(document.activeElement).toBe(checkbox("Creator 3"))
  })

  it("clear selection empties the batch", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
    say(intent({ kind: "select", select: { creator_ids: [], top_n: 5 } }))
    expect(trayCount()).toBe("5 selected")

    say(intent({ kind: "clear_selection" }))

    expect(
      screen.queryByRole("region", { name: "Selected creators" })
    ).toBeNull()
    expect(screen.queryAllByRole("checkbox", { checked: true })).toHaveLength(0)
    expect(loadSelection()).toEqual([])
  })

  it("the tray's Clear does the same", async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
    say(intent({ kind: "select", select: { creator_ids: [], top_n: 5 } }))

    await user.click(within(tray()).getByRole("button", { name: "Clear" }))

    expect(
      screen.queryByRole("region", { name: "Selected creators" })
    ).toBeNull()
  })

  it("open review goes to the comparison once there is a batch", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
    say(intent({ kind: "select", select: { creator_ids: [], top_n: 10 } }))

    say(intent({ kind: "open_review" }))

    expect(h.router.push).toHaveBeenCalledExactlyOnceWith(
      "/brand/discover/review"
    )
  })

  it("open review with nothing selected asks for a selection instead", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    say(intent({ kind: "open_review" }))

    expect(h.router.push).not.toHaveBeenCalled()
    expect(h.toastInfo).toHaveBeenCalledWith(
      "Select creators to review first",
      expect.anything()
    )
  })

  it("ignores intents that carry nothing to do", async () => {
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })
    const before = h.api.POST.mock.calls.length

    say(intent({ kind: "search" }))
    say(intent({ kind: "select" }))

    expect(h.api.POST.mock.calls.length).toBe(before)
    expect(
      screen.queryByRole("region", { name: "Selected creators" })
    ).toBeNull()
  })
})

describe("Discover: motion", () => {
  it("re-lays out the grid with the real animation when motion is welcome", async () => {
    stubMotionPreference(false)
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    searchReturns([creator(3), creator(1), ARJUN])
    say(intent({ search: { query: "reorder", limit: 24 } }))

    await screen.findByRole("group", { name: "Arjun Mehta" })
    expect(
      screen
        .getAllByRole("group")
        .map((el) => el.getAttribute("data-flip-id"))
        .filter(Boolean)
    ).toEqual(["creator-3", "creator-1", "creator-arjun"])
  })

  it("tray rises in with a tween when motion is welcome", async () => {
    stubMotionPreference(false)
    renderPage()
    await screen.findByRole("group", { name: "Creator 1" })

    say(intent({ kind: "select", select: { creator_ids: [], top_n: 3 } }))

    // Hidden at first (the tween starts from nothing), so not findable by role yet.
    const root = document.querySelector<HTMLElement>(
      "[data-slot=selection-tray]"
    )!
    expect(Number(root.style.opacity)).toBeLessThan(1)
    await waitFor(() => expect(root.style.opacity).toBe("1"), {
      timeout: 3000,
    })
    expect(trayCount()).toBe("3 selected")
  })
})

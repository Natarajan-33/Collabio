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

import ReviewPage from "@/app/brand/discover/review/page"
import { bestIndexes } from "@/components/deal/compare-table"
import { TooltipProvider } from "@/components/ui/tooltip"
import {
  VoiceScreenProvider,
  useVoiceRegistry,
  type VoiceIntent,
  type VoiceRegistry,
} from "@/components/voice/voice-screen"
import {
  bestFitPackage,
  loadSearch,
  loadSelection,
  saveSearch,
  saveSelection,
  type CreatorCard,
  type PackageSummary,
} from "@/lib/discover/state"

const h = vi.hoisted(() => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  router: { push: vi.fn() },
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("next/navigation", () => ({ useRouter: () => h.router }))

function pkg(over: Partial<PackageSummary> = {}): PackageSummary {
  return {
    id: "pkg",
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
    addons: [],
    ...over,
  }
}

function creator(n: number, ...packages: PackageSummary[]): CreatorCard {
  return {
    id: `creator-${n}`,
    handle: `handle${n}`,
    name: `Creator ${n}`,
    initials: `C${n}`,
    niches: ["consumer_tech"],
    region: "US",
    followers: 50000,
    engagement_rate: 4.1,
    packages: packages.length
      ? packages
      : [pkg({ id: `pkg-${n}`, name: `Pack ${n}` })],
  }
}

/** Three creators whose terms differ in every row. */
const THREE = [
  creator(
    1,
    pkg({
      id: "p1",
      name: "Pack 1",
      base_price_cents: 100000,
      per_video_cents: 50000,
      volume_count: 2,
      lead_time_days: 14,
      preferred_channel: "phone_ok",
    })
  ),
  creator(
    2,
    pkg({
      id: "p2",
      name: "Pack 2",
      base_price_cents: 150000,
      per_video_cents: 30000,
      volume_count: 5,
      lead_time_days: 7,
      preferred_channel: "email_first",
    })
  ),
  creator(
    3,
    pkg({
      id: "p3",
      name: "Pack 3",
      base_price_cents: 80000,
      per_video_cents: 80000,
      volume_count: 1,
      lead_time_days: null,
      preferred_channel: "email_only",
    })
  ),
]

function serve(creators: CreatorCard[]) {
  h.api.GET.mockImplementation(
    async (
      _path: string,
      init: { params: { path: { creator_id: string } } }
    ) => {
      const found = creators.find((c) => c.id === init.params.path.creator_id)
      return found
        ? { data: found, response: { status: 200 } }
        : { error: {}, response: { status: 404 } }
    }
  )
}

function intent(over: Partial<VoiceIntent>): VoiceIntent {
  return { kind: "search", heard: "", suggestions: [], ...over }
}

let registry: VoiceRegistry | null = null

function Probe() {
  const value = useVoiceRegistry()
  useEffect(() => {
    registry = value
  })
  return null
}

async function renderReview(
  ids: string[] = ["creator-1", "creator-2", "creator-3"]
) {
  saveSelection(ids)
  const view = render(
    <TooltipProvider delay={0}>
      <VoiceScreenProvider>
        <Probe />
        <ReviewPage />
      </VoiceScreenProvider>
    </TooltipProvider>
  )
  if (ids.length > 0) await screen.findByRole("table")
  return view
}

function say(spoken: VoiceIntent) {
  const handle = registry?.current()
  if (!handle) throw new Error("no page registered")
  act(() => handle.onIntent(spoken))
}

/** The figures in a row, one per creator, in column order. */
function row(label: string) {
  const el = screen.getByRole("row", { name: new RegExp(`^${label}`) })
  return within(el).getAllByRole("cell")
}

const texts = (cells: HTMLElement[]) =>
  cells.map((cell) => cell.textContent?.replace(/Best.*$/, "").trim())

const bestOf = (cells: HTMLElement[]) =>
  cells.map((cell) => cell.hasAttribute("data-best"))

function columnNames() {
  return screen
    .getAllByRole("columnheader")
    .slice(1)
    .map((header) => /Creator \d+/.exec(header.textContent ?? "")?.[0])
}

beforeEach(() => {
  h.api.GET.mockReset()
  h.router.push.mockReset()
  sessionStorage.clear()
  registry = null
  serve(THREE)
})

afterEach(cleanup)

describe("bestIndexes", () => {
  it("is the lowest or highest figure, ties included", () => {
    expect([...bestIndexes([3, 1, 2, 1], "lowest")]).toEqual([1, 3])
    expect([...bestIndexes([3, 1, 2, 3], "highest")]).toEqual([0, 3])
  })

  it("skips columns with no figure", () => {
    expect([...bestIndexes([null, 4, 2], "lowest")]).toEqual([2])
  })

  it("is nothing when there is nothing to compare or everyone agrees", () => {
    expect(bestIndexes([5], "lowest").size).toBe(0)
    expect(bestIndexes([null, 5, null], "lowest").size).toBe(0)
    expect(bestIndexes([5, 5, 5], "highest").size).toBe(0)
    expect(bestIndexes([], "lowest").size).toBe(0)
  })
})

describe("bestFitPackage", () => {
  const short = pkg({ id: "s", base_price_cents: 90000 })
  const long = pkg({
    id: "l",
    content_type: "long_video",
    base_price_cents: 280000,
  })
  const open = { niches: [], content_types: [] }

  it("is the first package the filters asked for", () => {
    const filters = { ...open, content_types: ["long_video" as const] }
    expect(bestFitPackage([short, long], filters)?.id).toBe("l")
  })

  it("is the cheapest package when the filters name none", () => {
    expect(bestFitPackage([short, long], open)?.id).toBe("s")
  })

  it("is the cheapest when none fits, and nothing when there are none", () => {
    const filters = { ...open, max_price_cents: 100 }
    expect(bestFitPackage([short, long], filters)?.id).toBe("s")
    expect(bestFitPackage([], open)).toBeNull()
  })
})

describe("Review: the comparison", () => {
  it("one column per selected creator, in the order they were picked", async () => {
    await renderReview(["creator-3", "creator-1"])

    expect(columnNames()).toEqual(["Creator 3", "Creator 1"])
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Compare your shortlist"
    )
    expect(h.api.GET).toHaveBeenCalledTimes(2)
    expect(h.api.GET).toHaveBeenCalledWith("/api/v1/creators/{creator_id}", {
      params: { path: { creator_id: "creator-3" } },
    })
  })

  it("compares ten at once", async () => {
    const ten = Array.from({ length: 10 }, (_, i) => creator(i + 1))
    serve(ten)

    await renderReview(ten.map((c) => c.id))

    expect(columnNames()).toHaveLength(10)
  })

  it("has a row each for package, price, per video, volume, lead time and channel", async () => {
    await renderReview()

    expect(
      screen.getAllByRole("rowheader").map((header) => header.textContent)
    ).toEqual([
      "Package",
      "Price",
      "Per video",
      "Volume",
      "Lead time",
      "Preferred channel",
    ])
    expect(texts(row("Package"))).toEqual([
      "Pack 1Short video",
      "Pack 2Short video",
      "Pack 3Short video",
    ])
    expect(texts(row("Price"))).toEqual(["$1,000", "$1,500", "$800"])
    expect(texts(row("Per video"))).toEqual(["$500", "$300", "$800"])
    expect(texts(row("Volume"))).toEqual([
      "2 videos / contract",
      "5 videos / contract",
      "1 video / contract",
    ])
    expect(texts(row("Lead time"))).toEqual(["14 days", "7 days", "—"])
    expect(texts(row("Preferred channel"))).toEqual([
      "Phone OK",
      "Email first",
      "Email only",
    ])
  })

  it("sets the figures in the figure face", async () => {
    await renderReview()

    expect(within(row("Price")[0]).getByText("$1,000").className).toContain(
      "num"
    )
  })

  it("marks the best value in each row", async () => {
    await renderReview()

    expect(bestOf(row("Price"))).toEqual([false, false, true])
    expect(bestOf(row("Per video"))).toEqual([false, true, false])
    expect(bestOf(row("Volume"))).toEqual([false, true, false])
    // A creator with no lead time stated is not "fastest".
    expect(bestOf(row("Lead time"))).toEqual([false, true, false])
    // Channel is not a number to beat.
    expect(bestOf(row("Preferred channel"))).toEqual([false, false, false])
    // Not by colour alone: the winner says so.
    expect(within(row("Price")[2]).getByText("Best")).toBeTruthy()
    expect(row("Price")[2].className).toContain("bg-gain")
  })

  it("highlights nothing when every creator offers the same", async () => {
    const same = [1, 2].map((n) => creator(n, pkg({ id: `s${n}` })))
    serve(same)

    await renderReview(["creator-1", "creator-2"])

    expect(bestOf(row("Price"))).toEqual([false, false])
    expect(screen.queryByText("Best")).toBeNull()
  })

  it("does not rank 3 a week against 3 in total", async () => {
    serve([
      creator(1, pkg({ id: "w", volume_count: 3, volume_basis: "per_week" })),
      creator(
        2,
        pkg({ id: "c", volume_count: 1, volume_basis: "per_contract" })
      ),
    ])

    await renderReview(["creator-1", "creator-2"])

    expect(texts(row("Volume"))).toEqual([
      "3 videos / week",
      "1 video / contract",
    ])
    expect(bestOf(row("Volume"))).toEqual([false, false])
  })

  it("start negotiation is disabled and says it is coming", async () => {
    const user = userEvent.setup()
    await renderReview()

    const button = screen.getByRole("button", {
      name: "Start negotiation",
    }) as HTMLButtonElement
    expect(button.disabled).toBe(true)

    await user.hover(button.parentElement!)
    await waitFor(() =>
      expect(
        document.querySelector("[data-slot=tooltip-content]")?.textContent
      ).toBe("Coming in M2")
    )
  })

  it("goes back to the creators", async () => {
    await renderReview()

    expect(
      screen
        .getByRole("link", { name: /Back to creators/ })
        .getAttribute("href")
    ).toBe("/brand/discover")
  })
})

describe("Review: choosing a package", () => {
  const two = creator(
    1,
    pkg({ id: "short", name: "Short", base_price_cents: 90000 }),
    pkg({
      id: "long",
      name: "Long",
      content_type: "long_video",
      base_price_cents: 280000,
    })
  )

  it("compares the package the search asked for", async () => {
    serve([two])
    saveSearch({
      query: null,
      filters: { niches: [], content_types: ["long_video"] },
      limit: 24,
    })

    await renderReview(["creator-1"])

    expect(
      (
        screen.getByRole("combobox", {
          name: "Package for Creator 1",
        }) as HTMLSelectElement
      ).value
    ).toBe("long")
    expect(texts(row("Price"))).toEqual(["$2,800"])
  })

  it("lets a creator's other package be compared instead", async () => {
    const user = userEvent.setup()
    serve([two, creator(2, pkg({ id: "x", base_price_cents: 100000 }))])
    await renderReview(["creator-1", "creator-2"])
    expect(bestOf(row("Price"))).toEqual([true, false])

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Package for Creator 1" }),
      "long"
    )

    expect(texts(row("Price"))).toEqual(["$2,800", "$1,000"])
    expect(bestOf(row("Price"))).toEqual([false, true])
  })

  it("shows no picker for a creator with one package", async () => {
    await renderReview()

    expect(screen.queryByRole("combobox")).toBeNull()
  })
})

describe("Review: editing the shortlist", () => {
  it("a column can be taken out", async () => {
    const user = userEvent.setup()
    await renderReview()

    await user.click(
      screen.getByRole("button", {
        name: "Remove Creator 2 from the comparison",
      })
    )

    expect(columnNames()).toEqual(["Creator 1", "Creator 3"])
    expect(loadSelection()).toEqual(["creator-1", "creator-3"])
  })

  it("taking out the last one leaves nothing to compare, with the way back", async () => {
    const user = userEvent.setup()
    await renderReview(["creator-1"])

    await user.click(
      screen.getByRole("button", {
        name: "Remove Creator 1 from the comparison",
      })
    )

    expect(screen.queryByRole("table")).toBeNull()
    expect(screen.getByText("Nothing to compare yet")).toBeTruthy()
    expect(
      screen
        .getAllByRole("link", { name: /Back to creators/ })[0]
        .getAttribute("href")
    ).toBe("/brand/discover")
  })

  it("nothing selected: says so, and fetches nothing", async () => {
    await renderReview([])

    expect(await screen.findByText("Nothing to compare yet")).toBeTruthy()
    expect(h.api.GET).not.toHaveBeenCalled()
    expect(
      (
        screen.getByRole("button", {
          name: "Start negotiation",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
  })

  it("a creator who is no longer in the marketplace drops out", async () => {
    serve([THREE[0], THREE[2]])

    await renderReview()

    expect(columnNames()).toEqual(["Creator 1", "Creator 3"])
    expect(loadSelection()).toEqual(["creator-1", "creator-3"])
  })
})

describe("Review: when creators will not load", () => {
  it("shows an error with a retry, and keeps the selection", async () => {
    const user = userEvent.setup()
    h.api.GET.mockResolvedValue({ error: {}, response: { status: 500 } })
    saveSelection(["creator-1", "creator-2"])
    render(
      <VoiceScreenProvider>
        <ReviewPage />
      </VoiceScreenProvider>
    )

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toContain("Couldn't load")
    expect(loadSelection()).toEqual(["creator-1", "creator-2"])

    serve(THREE)
    await user.click(within(alert).getByRole("button", { name: "Try again" }))

    await screen.findByRole("table")
    expect(columnNames()).toEqual(["Creator 1", "Creator 2"])
  })

  it("a network failure is an error too", async () => {
    h.api.GET.mockRejectedValue(new TypeError("fetch failed"))
    saveSelection(["creator-1"])
    render(
      <VoiceScreenProvider>
        <ReviewPage />
      </VoiceScreenProvider>
    )

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Couldn't load"
    )
  })
})

describe("Review: voice", () => {
  it("tells the dock which creators are compared", async () => {
    await renderReview()

    expect(registry?.current()?.screen).toBe("review")
    expect(registry?.current()?.getContext().visible_creators).toEqual([
      { id: "creator-1", name: "Creator 1", handle: "handle1" },
      { id: "creator-2", name: "Creator 2", handle: "handle2" },
      { id: "creator-3", name: "Creator 3", handle: "handle3" },
    ])
  })

  it("select the top two keeps the first two columns", async () => {
    await renderReview()

    say(intent({ kind: "select", select: { creator_ids: [], top_n: 2 } }))

    await waitFor(() =>
      expect(columnNames()).toEqual(["Creator 1", "Creator 2"])
    )
    expect(loadSelection()).toEqual(["creator-1", "creator-2"])
  })

  it("selecting creators by name keeps just those", async () => {
    await renderReview()

    say(
      intent({
        kind: "select",
        select: { creator_ids: ["creator-3", "creator-1"], top_n: null },
      })
    )

    await waitFor(() =>
      expect(columnNames()).toEqual(["Creator 1", "Creator 3"])
    )
  })

  it("selecting someone who is not compared changes nothing", async () => {
    await renderReview()

    say(
      intent({
        kind: "select",
        select: { creator_ids: ["somebody-else"], top_n: null },
      })
    )

    expect(columnNames()).toEqual(["Creator 1", "Creator 2", "Creator 3"])
  })

  it("clear selection empties the comparison", async () => {
    await renderReview()

    say(intent({ kind: "clear_selection" }))

    expect(await screen.findByText("Nothing to compare yet")).toBeTruthy()
    expect(loadSelection()).toEqual([])
  })

  it("a search goes back to Discover with the search applied", async () => {
    await renderReview()

    say(
      intent({
        kind: "search",
        search: {
          query: "beauty creators",
          filters: {
            niches: ["beauty"],
            content_types: [],
            max_price_cents: 100000,
          },
          limit: 24,
        },
      })
    )

    expect(h.router.push).toHaveBeenCalledExactlyOnceWith("/brand/discover")
    expect(loadSearch()).toEqual({
      query: "beauty creators",
      filters: {
        niches: ["beauty"],
        content_types: [],
        max_price_cents: 100000,
      },
      limit: 48,
    })
    // The batch goes with the brand.
    expect(loadSelection()).toEqual(["creator-1", "creator-2", "creator-3"])
  })

  it("open review is already open", async () => {
    await renderReview()

    say(intent({ kind: "open_review" }))

    expect(h.router.push).not.toHaveBeenCalled()
    expect(columnNames()).toHaveLength(3)
  })
})

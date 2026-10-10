import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  MAX_SELECTED,
  SELECTION_KEY,
  applySearchIntent,
  chipsFor,
  emptyDiscover,
  loadSearch,
  loadSelection,
  packageFits,
  removeFilter,
  saveSearch,
  saveSelection,
  selectionOverflow,
  selectionReducer,
  type CreatorCard,
  type DiscoverState,
  type PackageSummary,
} from "@/lib/discover/state"
import { formatEngagement, formatFollowers } from "@/lib/format"

function card(n: number): CreatorCard {
  return {
    id: `creator-${n}`,
    handle: `handle${n}`,
    name: `Creator ${n}`,
    initials: "C",
    niches: ["consumer_tech"],
    region: "US",
    followers: 1000 * n,
    engagement_rate: 4.2,
    packages: [],
  }
}

function withResults(count: number, over: Partial<DiscoverState> = {}) {
  return {
    ...emptyDiscover,
    results: Array.from({ length: count }, (_, i) => card(i + 1)),
    ...over,
  }
}

const ids = (count: number, from = 1) =>
  Array.from({ length: count }, (_, i) => `creator-${i + from}`)

describe("applySearchIntent and chipsFor", () => {
  it("search intent sets chips", () => {
    const s = applySearchIntent(emptyDiscover, {
      query: "short-form reviews",
      filters: {
        niches: ["consumer_tech"],
        content_types: ["short_video"],
        max_price_cents: 200000,
      },
    })

    expect(s.query).toBe("short-form reviews")
    expect(chipsFor(s.filters).map((c) => c.label)).toEqual([
      "Consumer tech",
      "Short video",
      "≤ $2,000",
    ])
  })

  it("replaces the previous query and filters, and keeps the selection and results", () => {
    const before: DiscoverState = {
      ...withResults(3),
      query: "old",
      filters: { niches: ["beauty"], content_types: [], region: "US" },
      selected: ["creator-2"],
    }

    const after = applySearchIntent(before, {
      query: "new",
      filters: { niches: ["gaming"] },
    })

    expect(after.query).toBe("new")
    expect(after.filters).toEqual({ niches: ["gaming"], content_types: [] })
    expect(after.selected).toEqual(["creator-2"])
    // The results stay until the new ones arrive.
    expect(after.results).toBe(before.results)
  })

  it("a search with no filters clears them", () => {
    const before: DiscoverState = {
      ...emptyDiscover,
      filters: { niches: ["beauty"], content_types: ["live"] },
    }

    const after = applySearchIntent(before, { query: "anything" })

    expect(chipsFor(after.filters)).toEqual([])
  })

  it("a blank query is no query", () => {
    expect(applySearchIntent(emptyDiscover, { query: "   " }).query).toBeNull()
    expect(applySearchIntent(emptyDiscover, { query: null }).query).toBeNull()
  })

  it("drops empty values so an unset filter is absent, not null", () => {
    const s = applySearchIntent(emptyDiscover, {
      filters: {
        niches: [],
        content_types: [],
        max_price_cents: null,
        min_followers: null,
        region: null,
      },
    })

    expect(s.filters).toEqual({ niches: [], content_types: [] })
    expect(Object.keys(s.filters)).toEqual(["niches", "content_types"])
  })

  it.each(["India", "", "  ", "us"])(
    "drops a region that is not a stored code (%j): the API would refuse it",
    (stale) => {
      const s = applySearchIntent(emptyDiscover, {
        filters: { region: stale as never },
      })

      expect(s.filters).toEqual({ niches: [], content_types: [] })
    }
  )

  it("names a region chip by its place, not its code", () => {
    const s = applySearchIntent(emptyDiscover, {
      filters: { region: "IN", niches: ["consumer_tech"] },
    })

    expect(s.filters.region).toBe("IN")
    expect(chipsFor(s.filters).map((c) => c.label)).toEqual([
      "Consumer tech",
      "India",
    ])
  })

  it("labels every kind of chip", () => {
    const chips = chipsFor({
      niches: ["b2b_saas", "food"],
      content_types: ["long_video", "story", "live"],
      max_price_cents: 99950,
      min_followers: 50000,
      region: "US",
    })

    expect(chips.map((c) => c.label)).toEqual([
      "B2B SaaS",
      "Food",
      "Long video",
      "Story",
      "Live",
      "≤ $999.50",
      "50k+ followers",
      "United States",
    ])
    // Stable, distinct keys.
    expect(new Set(chips.map((c) => c.id)).size).toBe(chips.length)
  })
})

describe("removeFilter", () => {
  const start: DiscoverState = {
    ...withResults(2),
    query: "reviews",
    selected: ["creator-1"],
    filters: {
      niches: ["consumer_tech", "gaming"],
      content_types: ["short_video"],
      max_price_cents: 200000,
      min_followers: 50000,
      region: "US",
    },
  }
  const chip = (label: string) =>
    chipsFor(start.filters).find((c) => c.label === label)!

  it("removing a chip clears that filter only", () => {
    const after = removeFilter(start, chip("≤ $2,000"))

    expect(after.filters).toEqual({
      niches: ["consumer_tech", "gaming"],
      content_types: ["short_video"],
      min_followers: 50000,
      region: "US",
    })
    expect(after.query).toBe("reviews")
    expect(after.selected).toEqual(["creator-1"])
    expect(after.results).toBe(start.results)
  })

  it("removing one niche keeps the others", () => {
    const after = removeFilter(start, chip("Consumer tech"))
    expect(after.filters.niches).toEqual(["gaming"])
    expect(after.filters.content_types).toEqual(["short_video"])
  })

  it("removing one format keeps the rest", () => {
    const two: DiscoverState = {
      ...start,
      filters: { ...start.filters, content_types: ["short_video", "story"] },
    }
    const after = removeFilter(
      two,
      chipsFor(two.filters).find((c) => c.label === "Story")!
    )
    expect(after.filters.content_types).toEqual(["short_video"])
  })

  it.each([
    ["50k+ followers", "min_followers"],
    ["United States", "region"],
  ] as const)("removes %s", (label, key) => {
    const after = removeFilter(start, chip(label))
    expect(key in after.filters).toBe(false)
  })

  it("does not change the state it was given", () => {
    const snapshot = structuredClone(start.filters)
    removeFilter(start, chip("Consumer tech"))
    expect(start.filters).toEqual(snapshot)
  })
})

describe("selectionReducer", () => {
  it("top_n selects first n results in order", () => {
    const after = selectionReducer(withResults(12), { type: "top_n", n: 5 })
    expect(after.selected).toEqual(ids(5))
  })

  it("top_n replaces whatever was selected", () => {
    const after = selectionReducer(
      withResults(12, { selected: ["creator-9", "creator-8"] }),
      { type: "top_n", n: 3 }
    )
    expect(after.selected).toEqual(ids(3))
  })

  it("top_n asks for more than there are: takes what there is", () => {
    const after = selectionReducer(withResults(4), { type: "top_n", n: 10 })
    expect(after.selected).toEqual(ids(4))
  })

  it("selection capped at 10", () => {
    const state = withResults(14)

    const top = selectionReducer(state, { type: "top_n", n: 14 })
    expect(top.selected).toEqual(ids(MAX_SELECTED))

    const added = selectionReducer(state, { type: "add", ids: ids(14) })
    expect(added.selected).toEqual(ids(MAX_SELECTED))
    expect(MAX_SELECTED).toBe(10)
  })

  it("a toggle at the cap does nothing", () => {
    const full = withResults(14, { selected: ids(10) })
    const after = selectionReducer(full, { type: "toggle", id: "creator-11" })
    expect(after.selected).toEqual(ids(10))
  })

  it("a toggle below the cap adds, and toggling again removes", () => {
    const on = selectionReducer(withResults(3), {
      type: "toggle",
      id: "creator-2",
    })
    expect(on.selected).toEqual(["creator-2"])

    const more = selectionReducer(on, { type: "toggle", id: "creator-1" })
    expect(more.selected).toEqual(["creator-2", "creator-1"])

    const off = selectionReducer(more, { type: "toggle", id: "creator-2" })
    expect(off.selected).toEqual(["creator-1"])
  })

  it("toggling off is always allowed, even at the cap", () => {
    const full = withResults(14, { selected: ids(10) })
    const after = selectionReducer(full, { type: "toggle", id: "creator-3" })
    expect(after.selected).toHaveLength(9)
  })

  it("add keeps order, skips what is already selected, and ignores duplicates", () => {
    const after = selectionReducer(
      withResults(5, { selected: ["creator-3"] }),
      { type: "add", ids: ["creator-1", "creator-3", "creator-1", "creator-2"] }
    )
    expect(after.selected).toEqual(["creator-3", "creator-1", "creator-2"])
  })

  it("clear empties the selection and nothing else", () => {
    const state = withResults(3, { selected: ids(3), query: "q" })
    const after = selectionReducer(state, { type: "clear" })
    expect(after.selected).toEqual([])
    expect(after.query).toBe("q")
    expect(after.results).toBe(state.results)
  })

  it("keeps the selection across a new search", () => {
    const picked = selectionReducer(withResults(5), { type: "top_n", n: 2 })
    const searched = applySearchIntent(picked, { query: "beauty" })
    expect(searched.selected).toEqual(ids(2))
  })
})

describe("selectionOverflow", () => {
  it("is true when an action wanted more than the cap allows", () => {
    const state = withResults(14)
    expect(selectionOverflow(state, { type: "top_n", n: 14 })).toBe(true)
    expect(selectionOverflow(state, { type: "add", ids: ids(11) })).toBe(true)
    expect(
      selectionOverflow(withResults(14, { selected: ids(10) }), {
        type: "toggle",
        id: "creator-11",
      })
    ).toBe(true)
  })

  it("is false when everything fit", () => {
    const state = withResults(14)
    expect(selectionOverflow(state, { type: "top_n", n: 10 })).toBe(false)
    expect(selectionOverflow(state, { type: "add", ids: ids(3) })).toBe(false)
    expect(selectionOverflow(state, { type: "toggle", id: "creator-1" })).toBe(
      false
    )
    expect(selectionOverflow(state, { type: "clear" })).toBe(false)
  })

  it("asking for ten when only four exist is not an overflow", () => {
    expect(selectionOverflow(withResults(4), { type: "top_n", n: 10 })).toBe(
      false
    )
  })

  it("re-adding what is selected is not an overflow", () => {
    const full = withResults(14, { selected: ids(10) })
    expect(selectionOverflow(full, { type: "add", ids: ids(10) })).toBe(false)
  })
})

describe("packageFits", () => {
  const pkg = (over: Partial<PackageSummary>): PackageSummary => ({
    id: "p",
    name: "Pack",
    content_type: "short_video",
    niche: "consumer_tech",
    volume_count: 2,
    volume_basis: "per_contract",
    base_price_cents: 100000,
    per_video_cents: 50000,
    one_liner: "",
    lead_time_days: 14,
    preferred_channel: "phone_ok",
    addons: [],
    ...over,
  })
  const open = { niches: [], content_types: [] }

  it("fits when the filters say nothing about packages", () => {
    expect(packageFits(pkg({}), open)).toBe(true)
    expect(packageFits(pkg({}), { ...open, region: "US" })).toBe(true)
  })

  it("checks the format and the price cap together", () => {
    const filters = {
      niches: [],
      content_types: ["short_video" as const],
      max_price_cents: 200000,
    }
    expect(packageFits(pkg({}), filters)).toBe(true)
    expect(packageFits(pkg({ content_type: "long_video" }), filters)).toBe(
      false
    )
    expect(packageFits(pkg({ base_price_cents: 200001 }), filters)).toBe(false)
    expect(packageFits(pkg({ base_price_cents: 200000 }), filters)).toBe(true)
  })
})

describe("storage", () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it("selected ids persist for the review page under collabio:selection", () => {
    saveSelection(["a", "b"])

    expect(SELECTION_KEY).toBe("collabio:selection")
    expect(sessionStorage.getItem("collabio:selection")).toBe('["a","b"]')
    expect(loadSelection()).toEqual(["a", "b"])
  })

  it("loads nothing when nothing was saved", () => {
    expect(loadSelection()).toEqual([])
    expect(loadSearch()).toBeNull()
  })

  it.each([
    ["not json", "{"],
    ["not an array", '{"a":1}'],
  ])("ignores a stored selection that is %s", (_name, raw) => {
    sessionStorage.setItem(SELECTION_KEY, raw)
    expect(loadSelection()).toEqual([])
  })

  it("keeps only text ids, without repeats, up to the cap", () => {
    sessionStorage.setItem(
      SELECTION_KEY,
      JSON.stringify(["a", 3, null, "a", ...ids(20)])
    )
    const loaded = loadSelection()
    expect(loaded.slice(0, 2)).toEqual(["a", "creator-1"])
    expect(loaded).toHaveLength(MAX_SELECTED)
  })

  it("the last search persists so Review can send the brand back to it", () => {
    const request = {
      query: "tech",
      filters: { niches: ["consumer_tech" as const], content_types: [] },
      limit: 24,
    }
    saveSearch(request)
    expect(loadSearch()).toEqual(request)
  })

  it("ignores a stored search that is not a search", () => {
    sessionStorage.setItem("collabio:search", '"nope"')
    expect(loadSearch()).toBeNull()
  })

  it("survives storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked")
    })
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked")
    })

    expect(() => saveSelection(["a"])).not.toThrow()
    expect(() => saveSearch({ query: null, limit: 24 })).not.toThrow()
    expect(loadSelection()).toEqual([])
    expect(loadSearch()).toBeNull()
  })
})

describe("formatFollowers", () => {
  it.each([
    [950, "950"],
    [1000, "1k"],
    [24000, "24k"],
    [78100, "78.1k"],
    [142000, "142k"],
    [142400, "142k"],
    [999999, "1M"],
    [1150000, "1.2M"],
    [2000000, "2M"],
  ])("%d reads %s", (n, text) => {
    expect(formatFollowers(n)).toBe(text)
  })
})

describe("formatEngagement", () => {
  it("shows percent points as a percentage", () => {
    expect(formatEngagement(5.8)).toBe("5.8%")
    expect(formatEngagement(8.9)).toBe("8.9%")
    expect(formatEngagement(4)).toBe("4%")
  })

  it("is a dash when the creator has none", () => {
    expect(formatEngagement(null)).toBe("—")
  })
})

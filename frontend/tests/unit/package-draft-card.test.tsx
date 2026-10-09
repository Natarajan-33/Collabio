import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useEffect, useState } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import PackagesPage from "@/app/creator/packages/page"
import { PackageDraftCard } from "@/components/deal/package-draft-card"
import {
  VoiceScreenProvider,
  useVoiceRegistry,
  type VoiceIntent,
  type VoiceRegistry,
} from "@/components/voice/voice-screen"
import {
  emptyDraft,
  type PackageDraft,
  type RuleViolation,
} from "@/lib/packages/draft"

const h = vi.hoisted(() => ({
  api: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), PUT: vi.fn() },
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

vi.mock("@/hooks/use-api", () => ({ useApi: () => h.api }))
vi.mock("sonner", () => ({ toast: h.toast }))
// CountUp watches for intersections, which jsdom cannot do; what it draws is not under
// test, only when the card asks for it.
vi.mock("@/components/ui/count-up", () => ({
  default: ({ from, to }: { from?: number; to: number }) => (
    <span data-testid="count-up" data-from={from} data-to={to} />
  ),
}))

// Fixtures ----------------------------------------------------------------------------

const NICHES = ["consumer_tech", "beauty"]

/** "short videos, tech, two per contract for nine hundred, extra video three fifty, email first" */
const SPOKEN: PackageDraft = {
  ...emptyDraft(),
  content_type: "short_video",
  niche: "consumer_tech",
  volume_count: 2,
  volume_basis: "per_contract",
  base_price_cents: 90000,
  preferred_channel: "email_first",
  addons: [{ name: "Extra video", price_cents: 35000, unit: "video" }],
}

const COMPLETE: PackageDraft = { ...SPOKEN, name: "Launch Duo" }

type CardProps = React.ComponentProps<typeof PackageDraftCard>

function setup(over: Partial<CardProps> = {}) {
  const handlers = {
    onChange: vi.fn(),
    onSave: vi.fn(),
    onPublish: vi.fn(),
    onFloorSave: vi.fn(),
    onDiscard: vi.fn(),
  }
  const props: CardProps = {
    draft: COMPLETE,
    missing: [],
    violations: [],
    niches: NICHES,
    ...handlers,
    ...over,
  }
  const view = render(<PackageDraftCard {...props} />)
  return { ...handlers, ...view, props }
}

/** The card with state behind it, for tests that type or click through several edits. */
function Harness({
  initial,
  onChange,
}: {
  initial: PackageDraft
  onChange?: (draft: PackageDraft) => void
}) {
  const [draft, setDraft] = useState(initial)
  return (
    <PackageDraftCard
      draft={draft}
      missing={[]}
      violations={[]}
      niches={NICHES}
      onChange={(next) => {
        setDraft(next)
        onChange?.(next)
      }}
      onSave={() => {}}
      onPublish={() => {}}
    />
  )
}

const field = (name: string) =>
  document.querySelector<HTMLElement>(`[data-field="${name}"]`)!
const button = (name: string | RegExp) =>
  screen.getByRole("button", { name }) as HTMLButtonElement

beforeEach(() => {
  for (const fn of [...Object.values(h.api), ...Object.values(h.toast)]) {
    fn.mockReset()
  }
})

afterEach(cleanup)

// The card ----------------------------------------------------------------------------

describe("PackageDraftCard: what the draft still needs", () => {
  it("missing fields are outlined and publish disabled", () => {
    setup({ draft: SPOKEN, missing: ["name"] })

    const name = field("name")
    expect(name.hasAttribute("data-missing")).toBe(true)
    expect(name.className).toContain("voice-missing")
    // Only what is missing is outlined.
    for (const done of ["content_type", "niche", "base_price_cents"]) {
      expect(field(done).hasAttribute("data-missing")).toBe(false)
    }
    expect(button("Publish").disabled).toBe(true)
    expect(button("Save draft").disabled).toBe(true)
  })

  it("outlines every missing field and names them in words", () => {
    setup({
      draft: emptyDraft(),
      missing: ["name", "content_type", "base_price_cents"],
    })

    for (const missing of ["name", "content_type", "base_price_cents"]) {
      expect(field(missing).hasAttribute("data-missing")).toBe(true)
    }
    expect(field("niche").hasAttribute("data-missing")).toBe(false)
    // The outline is not the only cue.
    expect(screen.getByText("Still needed: Name, Content type, Base price"))
    expect(within(field("name")).getByText("Needed")).toBeTruthy()
  })

  it("lets a complete draft be saved and published", async () => {
    const user = userEvent.setup()
    const { onSave, onPublish } = setup()

    expect(screen.queryByText(/still needed/i)).toBeNull()
    expect(button("Publish").disabled).toBe(false)
    expect(button("Save draft").disabled).toBe(false)

    await user.click(button("Save draft"))
    await user.click(button("Publish"))
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onPublish).toHaveBeenCalledTimes(1)
  })

  it("holds publishing back while a rule is broken, but still lets the draft be saved", () => {
    setup({
      violations: [{ field: "niche", message: "Pick one of your niches." }],
    })

    expect(button("Publish").disabled).toBe(true)
    expect(button("Save draft").disabled).toBe(false)
  })

  it("has nothing to save when nothing changed", () => {
    setup({ status: "draft", dirty: false })

    expect(button("Save draft").disabled).toBe(true)
    expect(button("Publish").disabled).toBe(false)
  })

  it("offers only changes to save once a package is published", () => {
    setup({ status: "published", dirty: true })

    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull()
    expect(button("Save changes").disabled).toBe(false)
    expect(screen.getByText("Published")).toBeTruthy()
  })

  it("locks the card while a save is in flight", () => {
    setup({ pending: "publish" })

    expect(button(/publishing/i).disabled).toBe(true)
    expect(button("Save draft").disabled).toBe(true)
    expect(screen.getByLabelText("Name").matches(":disabled")).toBe(true)
  })
})

describe("PackageDraftCard: violations", () => {
  const violations: RuleViolation[] = [
    { field: "niche", message: "Pick one of your niches (Consumer tech)." },
    { field: "base_price_cents", message: "Set a base price above $0." },
    { field: "addons", message: "Every add-on needs a price above $0." },
  ]

  it("violations render under their field", () => {
    setup({ violations })

    expect(
      within(field("niche")).getByText(
        "Pick one of your niches (Consumer tech)."
      )
    ).toBeTruthy()
    expect(
      within(field("base_price_cents")).getByText("Set a base price above $0.")
    ).toBeTruthy()
    expect(
      within(field("addons")).getByText("Every add-on needs a price above $0.")
    ).toBeTruthy()
    // Not under a field it does not belong to.
    expect(
      within(field("name")).queryByText("Set a base price above $0.")
    ).toBeNull()
  })

  it("ties a message to its control for assistive technology", () => {
    setup({ violations })

    const price = screen.getByLabelText("Base price") as HTMLInputElement
    expect(price.getAttribute("aria-invalid")).toBe("true")
    const message = document.getElementById(
      price.getAttribute("aria-describedby")!
    )
    expect(message?.textContent).toBe("Set a base price above $0.")
    expect(
      (screen.getByLabelText("Name") as HTMLInputElement).getAttribute(
        "aria-invalid"
      )
    ).toBeNull()
  })

  it("shows a message for a field the card does not have above the actions", () => {
    setup({ violations: [{ field: "currency", message: "Only USD for now." }] })

    expect(screen.getByText("Only USD for now.")).toBeTruthy()
  })
})

describe("PackageDraftCard: editing", () => {
  it("fills a text name", async () => {
    const user = userEvent.setup()
    const changes = vi.fn()
    render(<Harness initial={SPOKEN} onChange={changes} />)

    await user.type(screen.getByLabelText("Name"), "Launch Duo")

    expect(changes.mock.lastCall?.[0].name).toBe("Launch Duo")
  })

  it("picks content type, niche, volume basis and channel with chips", async () => {
    const user = userEvent.setup()
    const changes = vi.fn()
    render(<Harness initial={SPOKEN} onChange={changes} />)

    await user.click(button("Long video"))
    await user.click(button("Beauty"))
    await user.click(button("Per week"))
    await user.click(button("Phone OK"))

    const last = changes.mock.lastCall?.[0] as PackageDraft
    expect(last.content_type).toBe("long_video")
    expect(last.niche).toBe("beauty")
    expect(last.volume_basis).toBe("per_week")
    expect(last.preferred_channel).toBe("phone_ok")
    expect(button("Beauty").getAttribute("aria-pressed")).toBe("true")
    expect(button("Consumer tech").getAttribute("aria-pressed")).toBe("false")
  })

  it("offers only the creator's own niches", () => {
    setup()

    const niche = within(field("niche"))
    expect(niche.getByRole("button", { name: "Consumer tech" })).toBeTruthy()
    expect(niche.getByRole("button", { name: "Beauty" })).toBeTruthy()
    expect(niche.queryByRole("button", { name: "Gaming" })).toBeNull()
    expect(niche.queryByRole("button", { name: "Fitness" })).toBeNull()
  })

  it("steps the video count", async () => {
    const user = userEvent.setup()
    render(<Harness initial={SPOKEN} />)
    const videos = screen.getByRole("group", { name: "Videos" })

    expect(within(videos).getByText("2")).toBeTruthy()
    await user.click(button("Increase videos"))
    await user.click(button("Increase videos"))
    expect(within(videos).getByText("4")).toBeTruthy()
    await user.click(button("Decrease videos"))
    expect(within(videos).getByText("3")).toBeTruthy()
  })

  it("does not step the video count below one", async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ ...SPOKEN, volume_count: 1 }} />)

    expect(button("Decrease videos").disabled).toBe(true)
    await user.click(button("Decrease videos"))
    expect(
      within(screen.getByRole("group", { name: "Videos" })).getByText("1")
    ).toBeTruthy()
  })

  it("never fills in lead time or slots", () => {
    const { props } = setup({ draft: SPOKEN })

    expect(props.draft.lead_time_days).toBeUndefined()
    expect(
      within(screen.getByRole("group", { name: "Lead time" })).getByText(
        "Not set"
      )
    ).toBeTruthy()
    expect(
      within(screen.getByRole("group", { name: "Slots per month" })).getByText(
        "Not set"
      )
    ).toBeTruthy()
  })

  it("starts an optional stepper at one, and stepping down from one clears it", async () => {
    const user = userEvent.setup()
    const changes = vi.fn()
    render(<Harness initial={SPOKEN} onChange={changes} />)
    const lead = screen.getByRole("group", { name: "Lead time" })

    expect(button("Decrease lead time").disabled).toBe(true)
    await user.click(button("Increase lead time"))
    expect(within(lead).getByText("1")).toBeTruthy()
    expect(changes.mock.lastCall?.[0].lead_time_days).toBe(1)

    await user.click(button("Increase lead time"))
    await user.click(button("Decrease lead time"))
    await user.click(button("Decrease lead time"))
    expect(within(lead).getByText("Not set")).toBeTruthy()
    expect(changes.mock.lastCall?.[0].lead_time_days).toBeNull()
  })

  it("shows the base price in dollars and sends cents", async () => {
    const user = userEvent.setup()
    const changes = vi.fn()
    render(
      <Harness
        initial={{ ...SPOKEN, base_price_cents: null }}
        onChange={changes}
      />
    )
    const price = screen.getByLabelText("Base price") as HTMLInputElement

    await user.type(price, "999.5")
    expect(price.value).toBe("999.5")
    expect(changes.mock.lastCall?.[0].base_price_cents).toBe(99950)

    await user.clear(price)
    expect(changes.mock.lastCall?.[0].base_price_cents).toBeNull()
  })

  it("ignores characters that are not part of an amount", async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ ...SPOKEN, base_price_cents: null }} />)
    const price = screen.getByLabelText("Base price") as HTMLInputElement

    await user.type(price, "$1,2x0.555")

    expect(price.value).toBe("120.55")
  })

  it("shows a price that came from the draft in dollars", () => {
    setup({ draft: { ...SPOKEN, base_price_cents: 99950 } })

    expect(
      (screen.getByLabelText("Base price") as HTMLInputElement).value
    ).toBe("999.50")
  })

  it("adds, prices, names and removes add-ons", async () => {
    const user = userEvent.setup()
    const changes = vi.fn()
    render(<Harness initial={SPOKEN} onChange={changes} />)

    expect(
      (screen.getByLabelText("Add-on 1 name") as HTMLInputElement).value
    ).toBe("Extra video")
    expect(
      (screen.getByLabelText("Add-on 1 price") as HTMLInputElement).value
    ).toBe("350")

    await user.click(button("Add add-on"))
    await user.type(screen.getByLabelText("Add-on 2 name"), "Raw footage")
    await user.type(screen.getByLabelText("Add-on 2 price"), "75")
    expect(changes.mock.lastCall?.[0].addons).toEqual([
      { name: "Extra video", price_cents: 35000, unit: "video" },
      { name: "Raw footage", price_cents: 7500, unit: "video" },
    ])

    await user.selectOptions(screen.getByLabelText("Add-on 2 kind"), "item")
    expect(changes.mock.lastCall?.[0].addons[1].unit).toBe("item")

    await user.click(button("Remove add-on Extra video"))
    expect(changes.mock.lastCall?.[0].addons).toEqual([
      { name: "Raw footage", price_cents: 7500, unit: "item" },
    ])
    expect(screen.queryByLabelText("Add-on 2 name")).toBeNull()
  })

  it("shows what voice added to the other lists and lets it go", async () => {
    const user = userEvent.setup()
    const changes = vi.fn()
    render(
      <Harness
        initial={{
          ...SPOKEN,
          included: ["1 revision"],
          freebies: ["Free thumbnail"],
          extras: [{ name: "Thumbnail pack", price_cents: 5000 }],
        }}
        onChange={changes}
      />
    )

    expect(screen.getByText("1 revision")).toBeTruthy()
    expect(screen.getByText("Free thumbnail")).toBeTruthy()
    expect(screen.getByText("Thumbnail pack · $50")).toBeTruthy()

    await user.click(button("Remove extra Thumbnail pack"))
    expect(changes.mock.lastCall?.[0].extras).toEqual([])
    expect(screen.queryByText("Thumbnail pack · $50")).toBeNull()
  })
})

describe("PackageDraftCard: the price", () => {
  it("counts up to a new base price, but only when the price changes", () => {
    const { rerender, props } = setup({
      draft: { ...COMPLETE, base_price_cents: 90000 },
    })

    // First sight of a price: no count, just the number.
    expect(screen.queryByTestId("count-up")).toBeNull()
    expect(screen.getByText("Base price $900")).toBeTruthy()

    rerender(
      <PackageDraftCard
        {...props}
        draft={{ ...COMPLETE, base_price_cents: 95000 }}
      />
    )
    const counter = screen.getByTestId("count-up")
    expect(counter.getAttribute("data-from")).toBe("900")
    expect(counter.getAttribute("data-to")).toBe("950")
    expect(screen.getByText("Base price $950")).toBeTruthy()

    // The same price again, or a different field: nothing new to count.
    rerender(
      <PackageDraftCard
        {...props}
        draft={{ ...COMPLETE, name: "Other", base_price_cents: 95000 }}
      />
    )
    expect(screen.getByTestId("count-up").getAttribute("data-to")).toBe("950")
  })

  it("shows cents plainly instead of counting through them", () => {
    const { rerender, props } = setup({
      draft: { ...COMPLETE, base_price_cents: 90000 },
    })

    rerender(
      <PackageDraftCard
        {...props}
        draft={{ ...COMPLETE, base_price_cents: 99950 }}
      />
    )

    expect(screen.queryByTestId("count-up")).toBeNull()
    expect(screen.getByText("Base price $999.50")).toBeTruthy()
  })

  it("has no price to show until one is set", () => {
    setup({ draft: emptyDraft(), missing: ["base_price_cents"] })

    expect(screen.getByText("Base price not set")).toBeTruthy()
    expect(screen.queryByTestId("count-up")).toBeNull()
  })
})

describe("PackageDraftCard: the private floor", () => {
  const region = () => screen.getByRole("region", { name: /private/i })

  it("floor field shows private label", () => {
    setup({ status: "draft", floorCents: null })

    expect(
      within(region()).getByText("Private — only you see this")
    ).toBeTruthy()
    expect(region().querySelector("svg.lucide-lock")).toBeTruthy()
    expect(within(region()).getByLabelText("Floor price")).toBeTruthy()
  })

  it("keeps the floor out of the draft's own fields", () => {
    setup({ status: "draft" })

    expect(field("base_price_cents").contains(region())).toBe(false)
    expect(region().closest("[data-field]")).toBeNull()
  })

  it("shows the floor that is set", () => {
    setup({ status: "draft", floorCents: 80000 })

    expect(
      (screen.getByLabelText("Floor price") as HTMLInputElement).value
    ).toBe("800")
  })

  it("cannot be set until the package is saved", () => {
    setup({ status: null })

    expect(
      (screen.getByLabelText("Floor price") as HTMLInputElement).disabled
    ).toBe(true)
    expect(within(region()).getByText(/save the package first/i)).toBeTruthy()
  })

  it("refuses a floor above the base price before asking the server", async () => {
    const user = userEvent.setup()
    const { onFloorSave } = setup({ status: "draft", floorCents: null })
    const input = screen.getByLabelText("Floor price")

    await user.type(input, "1000")
    expect(
      within(region()).getByText(
        "Your floor can't be above the base price ($900)."
      )
    ).toBeTruthy()
    expect(input.getAttribute("aria-invalid")).toBe("true")
    expect(button("Set floor").disabled).toBe(true)

    await user.clear(input)
    await user.type(input, "800")
    expect(button("Set floor").disabled).toBe(false)
    await user.click(button("Set floor"))
    expect(onFloorSave).toHaveBeenCalledWith(80000)
  })

  it("accepts a floor equal to the base price", async () => {
    const user = userEvent.setup()
    const { onFloorSave } = setup({ status: "draft", floorCents: null })

    await user.type(screen.getByLabelText("Floor price"), "900")
    await user.click(button("Set floor"))

    expect(onFloorSave).toHaveBeenCalledWith(90000)
  })

  it("needs an amount above zero", async () => {
    const user = userEvent.setup()
    setup({ status: "draft", floorCents: null })

    expect(button("Set floor").disabled).toBe(true)
    await user.type(screen.getByLabelText("Floor price"), "0")
    expect(button("Set floor").disabled).toBe(true)
  })

  it("has nothing to set when the floor already stands", () => {
    setup({ status: "draft", floorCents: 80000 })

    expect(button("Set floor").disabled).toBe(true)
  })

  it("shows the server's reason under the floor", () => {
    setup({
      status: "draft",
      floorCents: null,
      violations: [
        {
          field: "floor_price_cents",
          message: "Your floor can't be above the base price ($900).",
        },
      ],
    })

    expect(
      within(region()).getByText(
        "Your floor can't be above the base price ($900)."
      )
    ).toBeTruthy()
  })

  it("does not outline the floor as missing, ever", () => {
    setup({ draft: emptyDraft(), missing: ["name", "base_price_cents"] })

    expect(region().querySelector("[data-missing]")).toBeNull()
  })
})

// The page ----------------------------------------------------------------------------

let registry: VoiceRegistry | null = null

function Probe() {
  const value = useVoiceRegistry()
  useEffect(() => {
    registry = value
  })
  return null
}

const ME = {
  user_id: "user-1",
  email: "priya@example.com",
  role: "creator",
  display_name: "Priya",
  brand: null,
  creator: {
    id: "creator-1",
    handle: "priya",
    name: "Priya",
    niches: ["consumer_tech", "beauty"],
    region: "US",
  },
}

function renderPage() {
  return render(
    <VoiceScreenProvider>
      <Probe />
      <PackagesPage />
    </VoiceScreenProvider>
  )
}

function say(spoken: Partial<VoiceIntent>) {
  const handle = registry?.current()
  if (!handle) throw new Error("no page registered")
  act(() =>
    handle.onIntent({
      kind: "package_draft",
      heard: "",
      suggestions: [],
      ...spoken,
    })
  )
}

describe("Packages page: voice", () => {
  beforeEach(() => {
    registry = null
    h.api.GET.mockImplementation(async (path: string) => ({
      data: path === "/api/v1/me" ? ME : [],
      response: { status: 200 },
    }))
  })

  it("registers as the packages screen", async () => {
    renderPage()
    await screen.findByText("Hold Space and describe your package")

    expect(registry?.current()?.screen).toBe("packages")
  })

  it("voice draft merges into the card", async () => {
    renderPage()
    await screen.findByText("Hold Space and describe your package")
    expect(screen.queryByRole("group", { name: "Videos" })).toBeNull()

    say({ package_draft: { ...emptyDraft(), volume_count: 2 } })

    const videos = await screen.findByRole("group", { name: "Videos" })
    expect(within(videos).getByText("2")).toBeTruthy()
  })

  it("fills the card from what was said, leaving only the name to give", async () => {
    renderPage()
    await screen.findByText("Hold Space and describe your package")

    say({ package_draft: SPOKEN })

    await screen.findByRole("group", { name: "Videos" })
    expect(button("Short video").getAttribute("aria-pressed")).toBe("true")
    expect(button("Consumer tech").getAttribute("aria-pressed")).toBe("true")
    expect(button("Per contract").getAttribute("aria-pressed")).toBe("true")
    expect(button("Email first").getAttribute("aria-pressed")).toBe("true")
    expect(
      (screen.getByLabelText("Base price") as HTMLInputElement).value
    ).toBe("900")
    expect(
      (screen.getByLabelText("Add-on 1 name") as HTMLInputElement).value
    ).toBe("Extra video")
    // Lead time was not said, so it is not made up.
    expect(
      within(screen.getByRole("group", { name: "Lead time" })).getByText(
        "Not set"
      )
    ).toBeTruthy()
    expect(field("name").hasAttribute("data-missing")).toBe(true)
    expect(document.querySelectorAll("[data-missing]")).toHaveLength(1)
    expect(button("Publish").disabled).toBe(true)
  })

  it("hands the open draft back to the router with the next command", async () => {
    renderPage()
    await screen.findByText("Hold Space and describe your package")
    expect(registry?.current()?.getContext().package_draft ?? null).toBeNull()

    say({ package_draft: { ...emptyDraft(), volume_count: 2 } })
    await screen.findByRole("group", { name: "Videos" })

    expect(registry?.current()?.getContext()).toEqual({
      visible_creators: [],
      package_draft: expect.objectContaining({ volume_count: 2 }),
    })
  })

  it("takes a later command as the draft with it merged in", async () => {
    renderPage()
    await screen.findByText("Hold Space and describe your package")
    say({ package_draft: { ...emptyDraft(), volume_count: 2 } })
    await screen.findByRole("group", { name: "Videos" })

    say({
      package_draft: {
        ...emptyDraft(),
        volume_count: 3,
        base_price_cents: 120000,
      },
    })

    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: "Videos" })).getByText("3")
      ).toBeTruthy()
    )
    expect(
      (screen.getByLabelText("Base price") as HTMLInputElement).value
    ).toBe("1200")
  })

  it("ignores a voice intent that carries no draft", async () => {
    renderPage()
    await screen.findByText("Hold Space and describe your package")

    say({ package_draft: null })

    expect(screen.queryByRole("group", { name: "Videos" })).toBeNull()
  })
})

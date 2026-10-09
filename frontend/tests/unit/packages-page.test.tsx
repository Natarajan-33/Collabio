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

import PackagesPage from "@/app/creator/packages/page"
import {
  VoiceScreenProvider,
  useVoiceRegistry,
  type VoiceIntent,
  type VoiceRegistry,
} from "@/components/voice/voice-screen"
import {
  emptyDraft,
  type MyPackage,
  type PackageDraft,
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
vi.mock("@/components/ui/count-up", () => ({
  default: ({ to }: { to: number }) => <span data-testid="count-up">{to}</span>,
}))

// Fixtures ----------------------------------------------------------------------------

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

function pkg(over: Partial<MyPackage> = {}): MyPackage {
  return {
    id: "pkg-1",
    name: "Launch Duo",
    content_type: "short_video",
    niche: "consumer_tech",
    volume_count: 2,
    volume_basis: "per_contract",
    base_price_cents: 90000,
    per_video_cents: 45000,
    one_liner: "2 videos/contract · $900 · +1 video $350",
    lead_time_days: null,
    preferred_channel: "email_first",
    addons: [{ name: "Extra video", price_cents: 35000, unit: "video" }],
    status: "published",
    floor_price_cents: 80000,
    currency: "USD",
    included: [],
    freebies: [],
    extras: [],
    slots_per_month: null,
    ...over,
  }
}

const PUBLISHED = pkg()
const DRAFTED = pkg({
  id: "pkg-2",
  name: "Deep Dive Review",
  content_type: "long_video",
  volume_count: 1,
  base_price_cents: 280000,
  per_video_cents: 280000,
  one_liner: "1 video/contract · $2,800",
  addons: [],
  status: "draft",
  floor_price_cents: null,
})

/** What was said: everything except the name. */
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

const ok = <T,>(data: T, status = 200) => ({
  data,
  response: { status, ok: true },
})
const rejected = (status: number, error?: unknown) => ({
  data: undefined,
  error,
  response: { status, ok: false },
})

let packages: MyPackage[]

function serve() {
  h.api.GET.mockImplementation(async (path: string) =>
    path === "/api/v1/me" ? ok(ME) : ok(packages)
  )
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

const button = (name: string | RegExp) =>
  screen.getByRole("button", { name }) as HTMLButtonElement
const field = (name: string) =>
  document.querySelector<HTMLElement>(`[data-field="${name}"]`)!
const ready = () => screen.findByText("Hold Space and describe your package")

/** Speaks the demo package, then types the name the speech left out. */
async function dictate(user: ReturnType<typeof userEvent.setup>) {
  await ready()
  say({ package_draft: SPOKEN })
  await user.type(await screen.findByLabelText("Name"), "Starter Pack")
}

beforeEach(() => {
  for (const fn of [...Object.values(h.api), ...Object.values(h.toast)]) {
    fn.mockReset()
  }
  registry = null
  packages = [PUBLISHED, DRAFTED]
  serve()
})

afterEach(cleanup)

// The list ----------------------------------------------------------------------------

describe("Packages page: the list", () => {
  it("asks for the packages and who the creator is", async () => {
    renderPage()
    await ready()

    const asked = h.api.GET.mock.calls.map((call) => call[0])
    expect(asked).toContain("/api/v1/me")
    expect(asked).toContain("/api/v1/me/packages")
  })

  it("shows each package with its status and terms", async () => {
    renderPage()
    await ready()

    expect(
      screen.getByRole("heading", { level: 1, name: "Your packages" })
    ).toBeTruthy()
    const launch = within(screen.getByRole("group", { name: "Launch Duo" }))
    expect(launch.getByText("Published")).toBeTruthy()
    expect(
      launch.getByText("2 videos/contract · $900 · +1 video $350")
    ).toBeTruthy()
    expect(launch.getByText("$450/video")).toBeTruthy()
    const deep = within(screen.getByRole("group", { name: "Deep Dive Review" }))
    expect(deep.getByText("Draft")).toBeTruthy()
    expect(deep.getByText("1 video/contract · $2,800")).toBeTruthy()
  })

  it("shows the private floor on a package that has one", async () => {
    renderPage()
    await ready()

    const launch = within(screen.getByRole("group", { name: "Launch Duo" }))
    expect(launch.getByText("Floor $800")).toBeTruthy()
    expect(launch.getByText("Only you see this")).toBeTruthy()
    const deep = within(screen.getByRole("group", { name: "Deep Dive Review" }))
    expect(deep.queryByText(/Floor/)).toBeNull()
  })

  it("invites the creator to describe a package", async () => {
    renderPage()

    expect(await ready()).toBeTruthy()
    expect(
      screen.getByText(/short videos, tech, two per contract/i)
    ).toBeTruthy()
    // Nothing is open until there is something to edit.
    expect(screen.queryByLabelText("Name")).toBeNull()
  })

  it("still invites when there are no packages yet", async () => {
    packages = []
    renderPage()

    expect(await ready()).toBeTruthy()
    expect(screen.getByText("No packages yet")).toBeTruthy()
  })

  it("says so when the packages cannot be loaded, and tries again", async () => {
    const user = userEvent.setup()
    h.api.GET.mockImplementation(async (path: string) =>
      path === "/api/v1/me" ? ok(ME) : rejected(500)
    )
    renderPage()

    expect(await screen.findByRole("alert")).toBeTruthy()
    expect(screen.getByText("Couldn't load your packages")).toBeTruthy()

    serve()
    await user.click(button("Try again"))
    expect(await ready()).toBeTruthy()
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("treats a network failure like any other failure to load", async () => {
    h.api.GET.mockRejectedValue(new TypeError("network"))
    renderPage()

    expect(await screen.findByText("Couldn't load your packages")).toBeTruthy()
  })
})

// The editor --------------------------------------------------------------------------

describe("Packages page: opening the editor", () => {
  it("starts a blank card from scratch with every required field outlined", async () => {
    const user = userEvent.setup()
    renderPage()
    await ready()

    await user.click(button("Start from scratch"))

    expect(screen.getByText("New")).toBeTruthy()
    expect(document.querySelectorAll("[data-missing]")).toHaveLength(7)
    expect(button("Publish").disabled).toBe(true)
  })

  it("offers only the creator's own niches", async () => {
    const user = userEvent.setup()
    renderPage()
    await ready()

    await user.click(button("Start from scratch"))

    const niche = within(field("niche"))
    expect(niche.getByRole("button", { name: "Consumer tech" })).toBeTruthy()
    expect(niche.getByRole("button", { name: "Beauty" })).toBeTruthy()
    expect(niche.queryByRole("button", { name: "Gaming" })).toBeNull()
  })

  it("opens a saved package for editing", async () => {
    const user = userEvent.setup()
    renderPage()
    await ready()

    await user.click(button("Edit Launch Duo"))

    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe(
      "Launch Duo"
    )
    expect(
      (screen.getByLabelText("Base price") as HTMLInputElement).value
    ).toBe("900")
    expect(
      (screen.getByLabelText("Floor price") as HTMLInputElement).value
    ).toBe("800")
    expect(document.querySelectorAll("[data-missing]")).toHaveLength(0)
    expect(button("Save changes").disabled).toBe(true)
  })

  it("lets a change be saved once it is made", async () => {
    const user = userEvent.setup()
    renderPage()
    await ready()
    await user.click(button("Edit Launch Duo"))

    await user.click(button("Increase videos"))

    expect(button("Save changes").disabled).toBe(false)
  })

  it("closes the card without saving anything", async () => {
    const user = userEvent.setup()
    renderPage()
    await ready()
    await user.click(button("Edit Launch Duo"))

    await user.click(button("Close"))

    expect(screen.queryByLabelText("Name")).toBeNull()
    expect(h.api.PATCH).not.toHaveBeenCalled()
    expect(h.api.POST).not.toHaveBeenCalled()
  })
})

describe("Packages page: voice dictation is only a preview", () => {
  it("saves nothing until the creator says so", async () => {
    renderPage()
    await ready()

    say({ package_draft: SPOKEN })
    await screen.findByLabelText("Name")

    expect(h.api.POST).not.toHaveBeenCalled()
    expect(h.api.PATCH).not.toHaveBeenCalled()
    expect(h.api.PUT).not.toHaveBeenCalled()
  })

  it("updates the card of a package being edited", async () => {
    const user = userEvent.setup()
    renderPage()
    await ready()
    await user.click(button("Edit Launch Duo"))

    say({
      package_draft: { ...SPOKEN, name: "Launch Duo", volume_count: 3 },
    })

    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: "Videos" })).getByText("3")
      ).toBeTruthy()
    )
    // Still that package: saving it would change it, not add another.
    expect(button("Save changes").disabled).toBe(false)
    expect(h.api.POST).not.toHaveBeenCalled()
  })

  it("holds a command back while the card is being saved", async () => {
    const user = userEvent.setup()
    let finish: (value: unknown) => void = () => {}
    h.api.POST.mockReturnValue(new Promise((resolve) => (finish = resolve)))
    renderPage()
    await dictate(user)

    await user.click(button("Save draft"))
    say({ package_draft: { ...SPOKEN, volume_count: 5 } })

    expect(h.toast.info).toHaveBeenCalledWith(
      expect.stringMatching(/finish saving/i),
      expect.anything()
    )
    await act(async () =>
      finish(
        ok(pkg({ id: "pkg-9", name: "Starter Pack", status: "draft" }), 201)
      )
    )
    expect(
      within(screen.getByRole("group", { name: "Videos" })).getByText("2")
    ).toBeTruthy()
  })
})

describe("Packages page: saving", () => {
  it("saves a new draft with the terms as dictated, and nothing invented", async () => {
    const user = userEvent.setup()
    const saved = pkg({
      id: "pkg-9",
      name: "Starter Pack",
      status: "draft",
      floor_price_cents: null,
    })
    h.api.POST.mockResolvedValue(ok(saved, 201))
    renderPage()
    await dictate(user)

    await user.click(button("Save draft"))

    await waitFor(() => expect(h.api.POST).toHaveBeenCalledTimes(1))
    const [path, init] = h.api.POST.mock.calls[0]
    expect(path).toBe("/api/v1/me/packages")
    expect(init.body).toEqual({
      name: "Starter Pack",
      content_type: "short_video",
      niche: "consumer_tech",
      volume_count: 2,
      volume_basis: "per_contract",
      base_price_cents: 90000,
      preferred_channel: "email_first",
      included: [],
      freebies: [],
      addons: [{ name: "Extra video", price_cents: 35000, unit: "video" }],
      extras: [],
    })
    expect(init.body).not.toHaveProperty("lead_time_days")
    expect(init.body).not.toHaveProperty("slots_per_month")
  })

  it("keeps the card open on the saved draft and adds it to the list", async () => {
    const user = userEvent.setup()
    const saved = pkg({
      id: "pkg-9",
      name: "Starter Pack",
      status: "draft",
      floor_price_cents: null,
    })
    h.api.POST.mockResolvedValue(ok(saved, 201))
    renderPage()
    await dictate(user)

    await user.click(button("Save draft"))

    await waitFor(() =>
      expect(h.toast.success).toHaveBeenCalledWith("Draft saved")
    )
    expect(
      within(screen.getByRole("group", { name: "Starter Pack" })).getByText(
        "Draft"
      )
    ).toBeTruthy()
    // Saved, so it can be published and can have a floor, and has nothing left to save.
    expect(button("Save draft").disabled).toBe(true)
    expect(button("Publish").disabled).toBe(false)
    expect(
      (screen.getByLabelText("Floor price") as HTMLInputElement).disabled
    ).toBe(false)
  })

  it("changes a saved package with PATCH, and toasts what the server warns about", async () => {
    const user = userEvent.setup()
    h.api.PATCH.mockResolvedValue(
      ok({
        ...PUBLISHED,
        volume_count: 3,
        warnings: ["search index update pending"],
      })
    )
    renderPage()
    await ready()
    await user.click(button("Edit Launch Duo"))
    await user.click(button("Increase videos"))

    await user.click(button("Save changes"))

    await waitFor(() => expect(h.api.PATCH).toHaveBeenCalledTimes(1))
    const [path, init] = h.api.PATCH.mock.calls[0]
    expect(path).toBe("/api/v1/me/packages/{package_id}")
    expect(init.params).toEqual({ path: { package_id: "pkg-1" } })
    expect(init.body.volume_count).toBe(3)
    // Cleared fields go as an explicit null so the server clears them.
    expect(init.body.lead_time_days).toBeNull()
    expect(h.api.POST).not.toHaveBeenCalled()
    await waitFor(() =>
      expect(h.toast.warning).toHaveBeenCalledWith(
        "search index update pending"
      )
    )
  })

  it("shows the rules a save breaks under their fields", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue(
      rejected(422, {
        detail: {
          error: "rules_violated",
          violations: [
            { field: "volume_count", message: "That number is too large." },
          ],
        },
      })
    )
    renderPage()
    await dictate(user)

    await user.click(button("Save draft"))

    expect(
      await within(field("volume_count")).findByText(
        "That number is too large."
      )
    ).toBeTruthy()
    expect(h.toast.error).toHaveBeenCalled()
    // Still unsaved: nothing was added.
    expect(screen.getByText("New")).toBeTruthy()
  })

  it("says so when the save cannot be made", async () => {
    const user = userEvent.setup()
    h.api.POST.mockRejectedValue(new TypeError("network"))
    renderPage()
    await dictate(user)

    await user.click(button("Save draft"))

    await waitFor(() =>
      expect(h.toast.error).toHaveBeenCalledWith(
        "Couldn't save the package. Try again.",
        expect.anything()
      )
    )
    expect(button("Save draft").disabled).toBe(false)
  })

  it("clears a stale rule message once the field is changed", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue(
      rejected(422, {
        detail: {
          error: "rules_violated",
          violations: [
            { field: "volume_count", message: "That number is too large." },
          ],
        },
      })
    )
    renderPage()
    await dictate(user)
    await user.click(button("Save draft"))
    await screen.findByText("That number is too large.")

    await user.click(button("Increase videos"))

    expect(screen.queryByText("That number is too large.")).toBeNull()
  })
})

describe("Packages page: publishing", () => {
  it("saves, then publishes, and the package shows as published", async () => {
    const user = userEvent.setup()
    h.api.POST.mockImplementation(async (path: string) =>
      path === "/api/v1/me/packages"
        ? ok(pkg({ id: "pkg-9", name: "Starter Pack", status: "draft" }), 201)
        : ok({
            ...pkg({ id: "pkg-9", name: "Starter Pack", status: "published" }),
            warnings: [],
          })
    )
    renderPage()
    await dictate(user)

    await user.click(button("Publish"))

    await waitFor(() => expect(h.api.POST).toHaveBeenCalledTimes(2))
    expect(h.api.POST.mock.calls[0][0]).toBe("/api/v1/me/packages")
    const [path, init] = h.api.POST.mock.calls[1]
    expect(path).toBe("/api/v1/me/packages/{package_id}/publish")
    expect(init.params).toEqual({ path: { package_id: "pkg-9" } })
    await waitFor(() =>
      expect(h.toast.success).toHaveBeenCalledWith(
        "Published. Brands can find it now."
      )
    )
    // Done with the card: the list shows the result.
    expect(screen.queryByLabelText("Name")).toBeNull()
    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: "Starter Pack" })).getByText(
          "Published"
        )
      ).toBeTruthy()
    )
  })

  it("publishes a saved draft without saving it again", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue(
      ok({ ...DRAFTED, status: "published", warnings: [] })
    )
    renderPage()
    await ready()
    await user.click(button("Edit Deep Dive Review"))
    // The saved package needs a niche from the creator's own: it has one.
    await user.click(button("Publish"))

    await waitFor(() => expect(h.api.POST).toHaveBeenCalledTimes(1))
    expect(h.api.POST.mock.calls[0][0]).toBe(
      "/api/v1/me/packages/{package_id}/publish"
    )
    expect(h.api.PATCH).not.toHaveBeenCalled()
  })

  it("saves the changes first when a saved draft was edited", async () => {
    const user = userEvent.setup()
    h.api.PATCH.mockResolvedValue(
      ok({ ...DRAFTED, volume_count: 2, warnings: [] })
    )
    h.api.POST.mockResolvedValue(
      ok({ ...DRAFTED, volume_count: 2, status: "published", warnings: [] })
    )
    renderPage()
    await ready()
    await user.click(button("Edit Deep Dive Review"))
    await user.click(button("Increase videos"))

    await user.click(button("Publish"))

    await waitFor(() => expect(h.api.POST).toHaveBeenCalledTimes(1))
    expect(h.api.PATCH).toHaveBeenCalledTimes(1)
    expect(
      h.api.PATCH.mock.invocationCallOrder[0] <
        h.api.POST.mock.invocationCallOrder[0]
    ).toBe(true)
  })

  it("shows the search index warning as a toast", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue(
      ok({
        ...DRAFTED,
        status: "published",
        warnings: ["search index update pending"],
      })
    )
    renderPage()
    await ready()
    await user.click(button("Edit Deep Dive Review"))

    await user.click(button("Publish"))

    await waitFor(() =>
      expect(h.toast.warning).toHaveBeenCalledWith(
        "search index update pending"
      )
    )
    expect(h.toast.success).toHaveBeenCalled()
  })

  it("keeps the saved draft and shows the rules when publishing is refused", async () => {
    const user = userEvent.setup()
    h.api.POST.mockImplementation(async (path: string) =>
      path === "/api/v1/me/packages"
        ? ok(pkg({ id: "pkg-9", name: "Starter Pack", status: "draft" }), 201)
        : rejected(422, {
            detail: {
              error: "rules_violated",
              violations: [
                {
                  field: "niche",
                  message: "Pick one of your niches (Beauty).",
                },
              ],
            },
          })
    )
    renderPage()
    await dictate(user)

    await user.click(button("Publish"))

    expect(
      await within(field("niche")).findByText(
        "Pick one of your niches (Beauty)."
      )
    ).toBeTruthy()
    expect(h.toast.error).toHaveBeenCalled()
    // It was saved on the way, and still is a draft.
    expect(
      within(screen.getByRole("group", { name: "Starter Pack" })).getByText(
        "Draft"
      )
    ).toBeTruthy()
    expect(screen.getByLabelText("Name")).toBeTruthy()
  })

  it("does not publish when the save in front of it fails", async () => {
    const user = userEvent.setup()
    h.api.POST.mockResolvedValue(rejected(500))
    renderPage()
    await dictate(user)

    await user.click(button("Publish"))

    await waitFor(() => expect(h.toast.error).toHaveBeenCalled())
    expect(h.api.POST).toHaveBeenCalledTimes(1)
  })
})

describe("Packages page: the private floor", () => {
  it("sets the floor of a saved package", async () => {
    const user = userEvent.setup()
    h.api.PUT.mockResolvedValue(ok({ ...DRAFTED, floor_price_cents: 250000 }))
    renderPage()
    await ready()
    await user.click(button("Edit Deep Dive Review"))

    await user.type(screen.getByLabelText("Floor price"), "2500")
    await user.click(button("Set floor"))

    await waitFor(() => expect(h.api.PUT).toHaveBeenCalledTimes(1))
    const [path, init] = h.api.PUT.mock.calls[0]
    expect(path).toBe("/api/v1/me/packages/{package_id}/floor")
    expect(init.params).toEqual({ path: { package_id: "pkg-2" } })
    expect(init.body).toEqual({ floor_price_cents: 250000 })
    await waitFor(() =>
      expect(
        within(
          screen.getByRole("group", { name: "Deep Dive Review" })
        ).getByText("Floor $2,500")
      ).toBeTruthy()
    )
    expect(h.toast.success).toHaveBeenCalledWith(
      "Floor saved. Only you can see it."
    )
  })

  it("shows the reason when the server refuses the floor", async () => {
    const user = userEvent.setup()
    h.api.PUT.mockResolvedValue(
      rejected(422, {
        detail: {
          error: "rules_violated",
          violations: [
            {
              field: "floor_price_cents",
              message: "Your floor can't be above the base price ($2,800).",
            },
          ],
        },
      })
    )
    renderPage()
    await ready()
    await user.click(button("Edit Deep Dive Review"))
    await user.type(screen.getByLabelText("Floor price"), "2500")

    await user.click(button("Set floor"))

    const panel = screen.getByRole("region", { name: /private/i })
    expect(
      await within(panel).findByText(
        "Your floor can't be above the base price ($2,800)."
      )
    ).toBeTruthy()
  })

  it("cannot be set before a new draft is saved", async () => {
    const user = userEvent.setup()
    renderPage()
    await ready()

    await user.click(button("Start from scratch"))

    expect(
      (screen.getByLabelText("Floor price") as HTMLInputElement).disabled
    ).toBe(true)
    expect(h.api.PUT).not.toHaveBeenCalled()
  })
})

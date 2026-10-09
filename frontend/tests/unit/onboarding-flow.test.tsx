import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { OnboardingFlow } from "@/components/auth/onboarding-flow"

const { router, api } = vi.hoisted(() => ({
  router: { replace: vi.fn(), refresh: vi.fn() },
  api: { POST: vi.fn() },
}))

vi.mock("next/navigation", () => ({ useRouter: () => router }))
vi.mock("@/hooks/use-api", () => ({ useApi: () => api }))

// BlurText and SpotlightCard observe intersections; jsdom has no IntersectionObserver.
class StubObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", StubObserver)
  router.replace.mockReset()
  router.refresh.mockReset()
  api.POST.mockReset()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type User = ReturnType<typeof userEvent.setup>

const ok = { response: { ok: true, status: 200 }, data: {} }

function conflict(code: string) {
  return { response: { ok: false, status: 409 }, error: { detail: code } }
}

async function chooseBrand(user: User) {
  await user.click(screen.getByRole("button", { name: "I sell products" }))
}

async function chooseCreator(user: User) {
  await user.click(screen.getByRole("button", { name: "I create content" }))
}

async function fillBrand(user: User) {
  await user.type(screen.getByLabelText("Company"), "Lumen")
  await user.click(screen.getByRole("button", { name: "Consumer tech" }))
  await user.type(screen.getByLabelText("Product name"), "Lumen Lamp")
  await user.type(
    screen.getByLabelText("One-line summary"),
    "A lamp that follows the sun"
  )
}

async function fillCreator(user: User) {
  await user.type(screen.getByLabelText("Your name"), "Priya Sharma")
  await user.type(screen.getByLabelText("Handle"), "priya.reviews")
  await user.click(screen.getByRole("button", { name: "Consumer tech" }))
  await user.selectOptions(screen.getByLabelText("Region"), "IN")
}

function finishButton() {
  return screen.getByRole("button", { name: /finish setup/i })
}

describe("OnboardingFlow role choice", () => {
  it("offers the two roles as large choices", () => {
    render(<OnboardingFlow />)

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /how will you use collabio/i,
      })
    ).toBeTruthy()
    expect(screen.getByRole("button", { name: "I sell products" })).toBeTruthy()
    expect(
      screen.getByRole("button", { name: "I create content" })
    ).toBeTruthy()
  })

  it("describes each choice to assistive tech", () => {
    render(<OnboardingFlow />)

    const brand = screen.getByRole("button", { name: "I sell products" })
    const describedBy = brand.getAttribute("aria-describedby")
    expect(describedBy).toBeTruthy()
    expect(document.getElementById(describedBy!)?.textContent).toMatch(
      /creators/i
    )
  })

  it("lets the user step back and pick the other role", async () => {
    const user = userEvent.setup()
    render(<OnboardingFlow />)

    await chooseBrand(user)
    await user.click(screen.getByRole("button", { name: /change role/i }))
    await chooseCreator(user)

    expect(screen.getByLabelText("Handle")).toBeTruthy()
  })
})

describe("OnboardingFlow brand", () => {
  it("keeps the finish button off until the form is complete", async () => {
    const user = userEvent.setup()
    render(<OnboardingFlow />)
    await chooseBrand(user)

    expect(finishButton().hasAttribute("disabled")).toBe(true)

    await fillBrand(user)
    expect(finishButton().hasAttribute("disabled")).toBe(false)
  })

  it("picks the category with chips, one at a time", async () => {
    const user = userEvent.setup()
    render(<OnboardingFlow />)
    await chooseBrand(user)

    const tech = screen.getByRole("button", { name: "Consumer tech" })
    const beauty = screen.getByRole("button", { name: "Beauty" })
    await user.click(tech)
    await user.click(beauty)

    expect(tech.getAttribute("aria-pressed")).toBe("false")
    expect(beauty.getAttribute("aria-pressed")).toBe("true")
  })

  it("onboards as a brand and goes to Discover", async () => {
    const user = userEvent.setup()
    api.POST.mockResolvedValue(ok)
    render(<OnboardingFlow />)
    await chooseBrand(user)
    await fillBrand(user)

    await user.click(finishButton())

    expect(api.POST).toHaveBeenCalledWith("/api/v1/onboarding", {
      body: {
        role: "brand",
        display_name: "Lumen",
        company_name: "Lumen",
        category: "consumer_tech",
        product_name: "Lumen Lamp",
        product_summary: "A lamp that follows the sun",
      },
    })
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/brand/discover")
    )
    expect(router.refresh).toHaveBeenCalled()
  })

  it("trims what was typed before sending it", async () => {
    const user = userEvent.setup()
    api.POST.mockResolvedValue(ok)
    render(<OnboardingFlow />)
    await chooseBrand(user)
    await fillBrand(user)
    await user.type(screen.getByLabelText("Company"), "   ")

    await user.click(finishButton())

    expect(api.POST.mock.calls[0][1].body.company_name).toBe("Lumen")
  })

  it("says so when the account already has a role", async () => {
    const user = userEvent.setup()
    api.POST.mockResolvedValue(conflict("role_locked"))
    render(<OnboardingFlow />)
    await chooseBrand(user)
    await fillBrand(user)

    await user.click(finishButton())

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toMatch(/already set up/i)
    expect(
      within(alert)
        .getByRole("link", { name: /go to your workspace/i })
        .getAttribute("href")
    ).toBe("/")
    expect(router.replace).not.toHaveBeenCalled()
  })
})

describe("OnboardingFlow creator", () => {
  it("onboards as a creator and goes to Packages", async () => {
    const user = userEvent.setup()
    api.POST.mockResolvedValue(ok)
    render(<OnboardingFlow />)
    await chooseCreator(user)
    await fillCreator(user)
    await user.click(screen.getByRole("button", { name: "Gaming" }))

    await user.click(finishButton())

    expect(api.POST).toHaveBeenCalledWith("/api/v1/onboarding", {
      body: {
        role: "creator",
        display_name: "Priya Sharma",
        handle: "priya.reviews",
        niches: ["consumer_tech", "gaming"],
        region: "IN",
      },
    })
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/creator/packages")
    )
  })

  it("needs at least one niche", async () => {
    const user = userEvent.setup()
    render(<OnboardingFlow />)
    await chooseCreator(user)
    await fillCreator(user)
    expect(finishButton().hasAttribute("disabled")).toBe(false)

    await user.click(screen.getByRole("button", { name: "Consumer tech" }))

    expect(finishButton().hasAttribute("disabled")).toBe(true)
  })

  it("offers the five launch regions", async () => {
    const user = userEvent.setup()
    render(<OnboardingFlow />)
    await chooseCreator(user)

    const options = within(screen.getByLabelText("Region")).getAllByRole(
      "option"
    )
    expect(options.map((o) => (o as HTMLOptionElement).value)).toEqual([
      "",
      "US",
      "IN",
      "UK",
      "CA",
      "AU",
    ])
  })

  it("cleans the handle as it is typed", async () => {
    const user = userEvent.setup()
    render(<OnboardingFlow />)
    await chooseCreator(user)

    const handle = screen.getByLabelText("Handle") as HTMLInputElement
    await user.type(handle, "@Priya Reviews!")

    expect(handle.value).toBe("priyareviews")
  })

  it("flags a taken handle on the handle field", async () => {
    const user = userEvent.setup()
    api.POST.mockResolvedValue(conflict("handle_taken"))
    render(<OnboardingFlow />)
    await chooseCreator(user)
    await fillCreator(user)

    await user.click(finishButton())

    const handle = screen.getByLabelText("Handle")
    await waitFor(() =>
      expect(handle.getAttribute("aria-invalid")).toBe("true")
    )
    const message = document.getElementById(
      handle.getAttribute("aria-describedby")!
    )
    expect(message?.textContent).toMatch(/@priya\.reviews is taken/i)
    expect(router.replace).not.toHaveBeenCalled()

    // Editing the handle clears the complaint.
    await user.type(handle, "x")
    expect(handle.getAttribute("aria-invalid")).toBeNull()
  })

  it("tells the user when the backend cannot be reached", async () => {
    const user = userEvent.setup()
    api.POST.mockRejectedValue(new TypeError("fetch failed"))
    render(<OnboardingFlow />)
    await chooseCreator(user)
    await fillCreator(user)

    await user.click(finishButton())

    expect((await screen.findByRole("alert")).textContent).toMatch(
      /can.t reach/i
    )
    expect(finishButton().hasAttribute("disabled")).toBe(false)
  })

  it("does not submit twice while the request is in flight", async () => {
    const user = userEvent.setup()
    api.POST.mockReturnValue(new Promise(() => {}))
    render(<OnboardingFlow />)
    await chooseCreator(user)
    await fillCreator(user)

    await user.click(finishButton())
    const busy = await screen.findByRole("button", { name: /setting up/i })
    await user.click(busy)

    expect(busy.hasAttribute("disabled")).toBe(true)
    expect(api.POST).toHaveBeenCalledTimes(1)
  })
})

import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AppShell } from "@/components/shell/app-shell"

const pathname = vi.hoisted(() => ({ current: "/brand/discover" }))
const { router, auth } = vi.hoisted(() => ({
  router: { replace: vi.fn(), refresh: vi.fn() },
  auth: { signOut: vi.fn() },
}))

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
  useRouter: () => router,
}))
vi.mock("@/lib/supabase/browser", () => ({
  getSupabaseBrowser: () => ({ auth }),
}))
// The dock has its own tests; here it only has to be mounted in the right place.
vi.mock("@/components/voice/voice-dock", () => ({
  VoiceDock: () => <div>voice dock</div>,
}))

beforeEach(() => {
  router.replace.mockReset()
  router.refresh.mockReset()
  auth.signOut.mockReset()
})

afterEach(() => {
  cleanup()
  pathname.current = "/brand/discover"
})

function primaryNav() {
  return screen.getByRole("navigation", { name: "Primary" })
}

describe("AppShell", () => {
  it("brand shell shows Discover only", () => {
    render(
      <AppShell role="brand">
        <p>page body</p>
      </AppShell>
    )

    const nav = primaryNav()
    const discover = within(nav).getByRole("link", { name: "Discover" })
    expect(discover.getAttribute("href")).toBe("/brand/discover")
    expect(discover.getAttribute("aria-current")).toBe("page")

    expect(within(nav).queryByText("Packages")).toBeNull()
    expect(within(nav).queryByText("Offers")).toBeNull()
    expect(within(nav).queryByText("Analytics")).toBeNull()
  })

  it("creator shell shows Packages and disabled Offers and Analytics", () => {
    pathname.current = "/creator/packages"
    render(
      <AppShell role="creator">
        <p>page body</p>
      </AppShell>
    )

    const nav = primaryNav()
    const packages = within(nav).getByRole("link", { name: "Packages" })
    expect(packages.getAttribute("href")).toBe("/creator/packages")
    expect(packages.getAttribute("aria-current")).toBe("page")
    expect(within(nav).queryByRole("link", { name: "Discover" })).toBeNull()

    for (const label of ["Offers", "Analytics"]) {
      const item = within(nav).getByText(label)
      expect(item.getAttribute("aria-disabled")).toBe("true")
      // Not navigable, and the reason is announced with the name.
      expect(item.getAttribute("href")).toBeNull()
      expect(item.getAttribute("aria-current")).toBeNull()
      expect(item.textContent).toContain("Soon")

      // The accessible name is the label alone; "Coming soon" is its description.
      const link = within(nav).getByRole("link", { name: label })
      expect(link).toBe(item)
      const note = document.getElementById(
        link.getAttribute("aria-describedby") ?? ""
      )
      expect(note?.textContent).toBe("Coming soon")
    }
  })

  it("renders the page body and mounts the Voice Dock outside the page", () => {
    render(
      <AppShell role="brand">
        <p>page body</p>
      </AppShell>
    )

    const main = screen.getByRole("main")
    expect(main.textContent).toContain("page body")
    const dock = screen.getByText("voice dock")
    expect(dock.closest("[data-slot='voice-dock']")).toBeTruthy()
    expect(main.contains(dock)).toBe(false)
  })

  it("signs out and returns to sign-in", async () => {
    const user = userEvent.setup()
    auth.signOut.mockResolvedValue({ error: null })
    render(<AppShell role="creator">x</AppShell>)

    await user.click(screen.getByRole("button", { name: "Sign out" }))

    expect(auth.signOut).toHaveBeenCalledTimes(1)
    expect(router.replace).toHaveBeenCalledWith("/sign-in")
    // Pages cached while signed in must not outlive the session.
    expect(router.refresh).toHaveBeenCalledTimes(1)
  })

  it("still leaves for sign-in if sign-out itself fails", async () => {
    const user = userEvent.setup()
    auth.signOut.mockRejectedValue(new Error("offline"))
    render(<AppShell role="brand">x</AppShell>)

    await user.click(screen.getByRole("button", { name: "Sign out" }))

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/sign-in")
    )
  })

  it("keeps sign-out out of the primary navigation", () => {
    render(<AppShell role="brand">x</AppShell>)

    expect(
      within(primaryNav()).queryByRole("button", { name: "Sign out" })
    ).toBeNull()
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy()
  })

  it("keeps the section active on nested routes", () => {
    pathname.current = "/brand/discover/review"
    render(<AppShell role="brand">x</AppShell>)
    expect(
      screen
        .getByRole("link", { name: "Discover" })
        .getAttribute("aria-current")
    ).toBe("page")
  })

  it("does not mark a section active on an unrelated path", () => {
    pathname.current = "/brand/discovery-lab"
    render(<AppShell role="brand">x</AppShell>)
    expect(
      screen
        .getByRole("link", { name: "Discover" })
        .getAttribute("aria-current")
    ).toBeNull()
  })
})

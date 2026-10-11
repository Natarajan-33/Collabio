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
vi.mock("@/components/voice/try-yourself-dialog", () => ({
  TryYourselfTrigger: () => <button type="button">Try it</button>,
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
  it("brand shell shows Discover and Board", () => {
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
  })

  it("brand rail links Board to /brand/batches", () => {
    pathname.current = "/brand/batches/abc"
    render(
      <AppShell role="brand">
        <p>page body</p>
      </AppShell>
    )

    const board = within(primaryNav()).getByRole("link", { name: "Board" })
    expect(board.getAttribute("href")).toBe("/brand/batches")
    expect(board.getAttribute("aria-current")).toBe("page")
    expect(
      within(primaryNav())
        .getByRole("link", { name: "Discover" })
        .getAttribute("aria-current")
    ).toBeNull()
    // Analytics is planned, not built.
    expect(
      within(primaryNav()).getByText("Analytics").getAttribute("aria-disabled")
    ).toBe("true")
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

  it("forgets the selection and last search, which belong to the account that made them", async () => {
    const user = userEvent.setup()
    auth.signOut.mockResolvedValue({ error: null })
    sessionStorage.setItem("collabio:selection", '["creator-1"]')
    sessionStorage.setItem("collabio:search", '{"query":"tech"}')
    sessionStorage.setItem("unrelated", "kept")
    render(<AppShell role="brand">x</AppShell>)

    await user.click(screen.getByRole("button", { name: "Sign out" }))

    expect(sessionStorage.getItem("collabio:selection")).toBeNull()
    expect(sessionStorage.getItem("collabio:search")).toBeNull()
    expect(sessionStorage.getItem("unrelated")).toBe("kept")
    sessionStorage.clear()
  })

  it("forgets them even when sign-out itself fails", async () => {
    const user = userEvent.setup()
    auth.signOut.mockRejectedValue(new Error("offline"))
    sessionStorage.setItem("collabio:selection", '["creator-1"]')
    render(<AppShell role="brand">x</AppShell>)

    await user.click(screen.getByRole("button", { name: "Sign out" }))

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/sign-in")
    )
    expect(sessionStorage.getItem("collabio:selection")).toBeNull()
  })

  it("still leaves for sign-in when session storage is unavailable", async () => {
    const user = userEvent.setup()
    auth.signOut.mockResolvedValue({ error: null })
    const blocked = vi
      .spyOn(Storage.prototype, "removeItem")
      .mockImplementation(() => {
        throw new DOMException("denied", "SecurityError")
      })
    render(<AppShell role="brand">x</AppShell>)

    await user.click(screen.getByRole("button", { name: "Sign out" }))

    expect(router.replace).toHaveBeenCalledWith("/sign-in")
    blocked.mockRestore()
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

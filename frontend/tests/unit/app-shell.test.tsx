import { cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AppShell } from "@/components/shell/app-shell"

const pathname = vi.hoisted(() => ({ current: "/brand/discover" }))

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
}))

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

  it("renders the page body and the Voice Dock slot", () => {
    render(
      <AppShell role="brand" dock={<div>dock goes here</div>}>
        <p>page body</p>
      </AppShell>
    )

    expect(screen.getByRole("main").textContent).toContain("page body")
    expect(screen.getByText("dock goes here")).toBeTruthy()
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

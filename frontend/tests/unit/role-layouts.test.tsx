import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import BrandLayout from "@/app/brand/layout"
import CreatorLayout from "@/app/creator/layout"
import Home from "@/app/page"
import { SessionError } from "@/components/auth/session-error"

const { router, auth, guardRoute, getMe, useCreatorDoorbell } = vi.hoisted(
  () => ({
    useCreatorDoorbell: vi.fn(),
    router: { replace: vi.fn(), refresh: vi.fn() },
    auth: { signOut: vi.fn() },
    guardRoute: vi.fn(),
    getMe: vi.fn(),
  })
)

class Redirected extends Error {
  constructor(readonly to: string) {
    super(`redirect:${to}`)
  }
}

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/brand/discover",
  redirect: (to: string) => {
    throw new Redirected(to)
  },
}))
vi.mock("@/lib/supabase/browser", () => ({
  getSupabaseBrowser: () => ({ auth }),
}))
vi.mock("@/hooks/use-api", () => ({
  useApi: () => ({
    GET: async () => ({
      data: { needs_you: 0, waiting: 0, booked: 0, closed: 0 },
    }),
  }),
}))
vi.mock("@/lib/supabase/realtime", () => ({ useCreatorDoorbell }))
vi.mock("@/lib/auth/guard", () => ({ guardRoute }))
vi.mock("@/lib/auth/me", () => ({ getMe }))
// The dock needs the API client and a microphone; these tests are about the layouts.
vi.mock("@/components/voice/voice-dock", () => ({ VoiceDock: () => null }))
vi.mock("@/components/voice/try-yourself-dialog", () => ({
  TryYourselfTrigger: () => null,
}))

beforeEach(() => {
  router.replace.mockReset()
  router.refresh.mockReset()
  auth.signOut.mockReset()
  guardRoute.mockReset()
  getMe.mockReset()
  useCreatorDoorbell.mockReset()
})

afterEach(cleanup)

describe("role layouts", () => {
  it("brand layout guards /brand and wraps the page in the brand shell", async () => {
    guardRoute.mockResolvedValue({ kind: "ok", me: {} })

    render(await BrandLayout({ children: <p>page body</p> }))

    expect(guardRoute).toHaveBeenCalledWith("/brand")
    expect(screen.getByText("page body")).toBeTruthy()
    expect(
      screen.getByRole("link", { name: "Discover" }).getAttribute("href")
    ).toBe("/brand/discover")
  })

  it("creator layout guards /creator and wraps the page in the creator shell", async () => {
    guardRoute.mockResolvedValue({ kind: "ok", me: {} })

    render(await CreatorLayout({ children: <p>page body</p> }))

    expect(guardRoute).toHaveBeenCalledWith("/creator")
    expect(screen.getByText("page body")).toBeTruthy()
    expect(
      screen.getByRole("link", { name: "Packages" }).getAttribute("href")
    ).toBe("/creator/packages")
  })

  it("creator layout hands the shell the creator's id for the realtime doorbell", async () => {
    guardRoute.mockResolvedValue({
      kind: "ok",
      me: { creator: { id: "creator-7" } },
    })

    render(await CreatorLayout({ children: <p>page body</p> }))

    expect(useCreatorDoorbell).toHaveBeenCalledWith(
      "creator-7",
      expect.any(Function)
    )
  })

  it.each([
    ["brand", BrandLayout],
    ["creator", CreatorLayout],
  ])(
    "%s layout shows an error state, not the app, when the backend is down",
    async (_role, Layout) => {
      guardRoute.mockResolvedValue({
        kind: "unavailable",
        reason: "unreachable",
      })

      render(await Layout({ children: <p>page body</p> }))

      expect(
        screen.getByRole("heading", { name: /can.t reach collabio/i })
      ).toBeTruthy()
      expect(screen.queryByText("page body")).toBeNull()
      expect(screen.queryByRole("navigation", { name: "Primary" })).toBeNull()
    }
  )

  it("lets the redirect from the guard through", async () => {
    guardRoute.mockRejectedValue(new Redirected("/onboarding"))

    await expect(BrandLayout({ children: null })).rejects.toMatchObject({
      to: "/onboarding",
    })
  })
})

describe("home page", () => {
  const me = (role: "brand" | "creator" | null) => ({
    kind: "ok" as const,
    me: { role },
  })

  it.each([
    ["brand", "/brand/discover"],
    ["creator", "/creator/packages"],
    [null, "/onboarding"],
  ] as const)("sends a %s user to %s", async (role, to) => {
    getMe.mockResolvedValue(me(role))

    await expect(Home()).rejects.toMatchObject({ to })
  })

  it("sends an anonymous visitor to sign-in", async () => {
    getMe.mockResolvedValue({ kind: "anonymous" })

    await expect(Home()).rejects.toMatchObject({ to: "/sign-in" })
  })

  it("shows an error state when the backend is down", async () => {
    getMe.mockResolvedValue({ kind: "unavailable", reason: "error" })

    render(await Home())

    expect(
      screen.getByRole("heading", { name: /went wrong on our side/i })
    ).toBeTruthy()
  })
})

describe("SessionError", () => {
  it("retries by refreshing the page", async () => {
    const user = userEvent.setup()
    render(<SessionError reason="unreachable" />)

    await user.click(screen.getByRole("button", { name: "Try again" }))

    expect(router.refresh).toHaveBeenCalledTimes(1)
    expect(auth.signOut).not.toHaveBeenCalled()
  })

  it("signs out and returns to sign-in", async () => {
    const user = userEvent.setup()
    auth.signOut.mockResolvedValue({ error: null })
    render(<SessionError reason="error" />)

    await user.click(screen.getByRole("button", { name: "Sign out" }))

    expect(auth.signOut).toHaveBeenCalledTimes(1)
    expect(router.replace).toHaveBeenCalledWith("/sign-in")
  })

  it("still leaves for sign-in if sign-out itself fails", async () => {
    const user = userEvent.setup()
    auth.signOut.mockRejectedValue(new Error("offline"))
    render(<SessionError reason="unreachable" />)

    await user.click(screen.getByRole("button", { name: "Sign out" }))

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/sign-in")
    )
  })
})

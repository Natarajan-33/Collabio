import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import SignInPage from "@/app/(auth)/sign-in/page"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}))
vi.mock("@/lib/supabase/browser", () => ({ getSupabaseBrowser: () => ({}) }))

async function renderPage(next?: string) {
  render(await SignInPage({ searchParams: Promise.resolve({ next }) }))
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1")
  vi.stubEnv("DEMO_BRAND_EMAIL", "shop@demo.test")
  vi.stubEnv("DEMO_HELPER_EMAIL", "ana.helper@demo.test")
})

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

describe("sign-in page demo hint", () => {
  it("lists the accounts named by DEMO_BRAND_EMAIL and DEMO_HELPER_EMAIL", async () => {
    await renderPage()

    const hint = screen.getByRole("complementary", { name: /demo accounts/i })
    expect(hint.textContent).toContain("shop@demo.test")
    expect(hint.textContent).toContain("ana.helper@demo.test")
    expect(hint.textContent).toContain("ana.helper+arjun@demo.test")
    // Nothing is hard-coded: the old seeded addresses are gone.
    expect(hint.textContent).not.toContain("lumen.brand@example.com")
    expect(hint.textContent).not.toContain("helper.creator@example.com")
    expect(hint.textContent).not.toMatch(/password/i)
  })

  it("follows the environment at request time", async () => {
    vi.stubEnv("DEMO_BRAND_EMAIL", "other.brand@demo.test")

    await renderPage()

    expect(
      screen.getByRole("complementary", { name: /demo accounts/i }).textContent
    ).toContain("other.brand@demo.test")
  })

  it("is hidden when the demo variables are unset", async () => {
    vi.stubEnv("DEMO_BRAND_EMAIL", "")
    vi.stubEnv("DEMO_HELPER_EMAIL", "")

    await renderPage()

    expect(screen.queryByRole("complementary")).toBeNull()
  })

  it("is hidden outside demo mode even when the emails are set", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "0")

    await renderPage()

    expect(screen.queryByRole("complementary")).toBeNull()
    expect(screen.queryByText(/shop@demo\.test/)).toBeNull()
  })
})

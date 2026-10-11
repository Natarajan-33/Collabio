import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import SignInPage from "@/app/(auth)/sign-in/page"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}))
vi.mock("@/lib/supabase/browser", () => ({ getSupabaseBrowser: () => ({}) }))

async function renderPage(next?: string) {
  render(await SignInPage({ searchParams: Promise.resolve({ next }) }))
}

afterEach(cleanup)

describe("sign-in page", () => {
  it("does not list demo account emails", async () => {
    await renderPage()
    expect(screen.queryByRole("complementary", { name: /demo accounts/i })).toBeNull()
    expect(screen.getByRole("heading", { name: /welcome back/i })).toBeTruthy()
  })
})

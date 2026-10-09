import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { CredentialsForm } from "@/components/auth/credentials-form"

const { router, auth } = vi.hoisted(() => ({
  router: { replace: vi.fn(), refresh: vi.fn() },
  auth: { signInWithPassword: vi.fn(), signUp: vi.fn() },
}))

vi.mock("next/navigation", () => ({ useRouter: () => router }))
vi.mock("@/lib/supabase/browser", () => ({
  getSupabaseBrowser: () => ({ auth }),
}))

beforeEach(() => {
  router.replace.mockReset()
  router.refresh.mockReset()
  auth.signInWithPassword.mockReset()
  auth.signUp.mockReset()
})

afterEach(cleanup)

async function fillAndSubmit(
  user: ReturnType<typeof userEvent.setup>,
  button: RegExp
) {
  await user.type(screen.getByLabelText("Email"), "priya@example.com")
  await user.type(screen.getByLabelText("Password"), "hunter2-hunter2")
  await user.click(screen.getByRole("button", { name: button }))
}

describe("CredentialsForm sign-in", () => {
  it("signs in and goes to the requested page", async () => {
    const user = userEvent.setup()
    auth.signInWithPassword.mockResolvedValue({ data: {}, error: null })
    render(<CredentialsForm mode="sign-in" next="/creator/packages" />)

    await fillAndSubmit(user, /^sign in$/i)

    expect(auth.signInWithPassword).toHaveBeenCalledWith({
      email: "priya@example.com",
      password: "hunter2-hunter2",
    })
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/creator/packages")
    )
    // The router cache may still hold pages fetched while signed out.
    expect(router.refresh).toHaveBeenCalled()
  })

  it("goes to the root, which routes by role, when there is no next", async () => {
    const user = userEvent.setup()
    auth.signInWithPassword.mockResolvedValue({ data: {}, error: null })
    render(<CredentialsForm mode="sign-in" />)

    await fillAndSubmit(user, /^sign in$/i)

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"))
  })

  it("explains wrong credentials in plain words and stays put", async () => {
    const user = userEvent.setup()
    auth.signInWithPassword.mockResolvedValue({
      data: {},
      error: {
        code: "invalid_credentials",
        name: "AuthApiError",
        message: "Invalid login credentials",
      },
    })
    render(<CredentialsForm mode="sign-in" />)

    await fillAndSubmit(user, /^sign in$/i)

    expect((await screen.findByRole("alert")).textContent).toMatch(
      /email and password don.t match/i
    )
    expect(router.replace).not.toHaveBeenCalled()
    // The form is usable again.
    expect(
      screen
        .getByRole("button", { name: /^sign in$/i })
        .hasAttribute("disabled")
    ).toBe(false)
  })

  it("tells the user when the sign-in service cannot be reached", async () => {
    const user = userEvent.setup()
    auth.signInWithPassword.mockResolvedValue({
      data: {},
      error: { name: "AuthRetryableFetchError", message: "fetch failed" },
    })
    render(<CredentialsForm mode="sign-in" />)

    await fillAndSubmit(user, /^sign in$/i)

    expect((await screen.findByRole("alert")).textContent).toMatch(
      /can.t reach/i
    )
  })

  it("does not submit twice while a sign-in is in flight", async () => {
    const user = userEvent.setup()
    auth.signInWithPassword.mockReturnValue(new Promise(() => {}))
    render(<CredentialsForm mode="sign-in" />)

    await fillAndSubmit(user, /^sign in$/i)

    const busy = await screen.findByRole("button", { name: /signing in/i })
    expect(busy.hasAttribute("disabled")).toBe(true)
    await user.click(busy)
    expect(auth.signInWithPassword).toHaveBeenCalledTimes(1)
  })

  it("links to sign-up", () => {
    render(<CredentialsForm mode="sign-in" />)

    expect(
      screen
        .getByRole("link", { name: /create an account/i })
        .getAttribute("href")
    ).toBe("/sign-up")
  })
})

describe("CredentialsForm demo hint", () => {
  // Whatever the server derived from the environment; nothing is built in.
  const accounts = [
    { email: "shop@demo.test", who: "Brand · Lumen" },
    { email: "ana.helper@demo.test", who: "Creator · Priya" },
    { email: "ana.helper+arjun@demo.test", who: "Creator · Arjun" },
  ]

  it("lists the accounts it is given, never a password", () => {
    render(<CredentialsForm mode="sign-in" demoAccounts={accounts} />)

    const hint = screen.getByRole("complementary", { name: /demo accounts/i })
    expect(hint.textContent).toContain("shop@demo.test")
    expect(hint.textContent).toContain("ana.helper@demo.test")
    expect(hint.textContent).toContain("ana.helper+arjun@demo.test")
    expect(hint.textContent).not.toMatch(/password/i)
  })

  it("fills the email field when an account is picked", async () => {
    const user = userEvent.setup()
    render(<CredentialsForm mode="sign-in" demoAccounts={accounts} />)

    await user.click(
      screen.getByRole("button", { name: /ana\.helper@demo\.test/i })
    )

    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe(
      "ana.helper@demo.test"
    )
    // Only the password is left to type.
    expect(document.activeElement).toBe(screen.getByLabelText("Password"))
  })

  it("is absent without accounts", () => {
    render(<CredentialsForm mode="sign-in" />)
    expect(screen.queryByRole("complementary")).toBeNull()

    cleanup()
    render(<CredentialsForm mode="sign-in" demoAccounts={[]} />)
    expect(screen.queryByRole("complementary")).toBeNull()
  })

  it("is not shown on sign-up", () => {
    render(<CredentialsForm mode="sign-up" demoAccounts={accounts} />)

    expect(screen.queryByRole("complementary")).toBeNull()
  })
})

describe("CredentialsForm sign-up", () => {
  it("creates the account and continues to onboarding", async () => {
    const user = userEvent.setup()
    auth.signUp.mockResolvedValue({
      data: { session: { access_token: "t" }, user: {} },
      error: null,
    })
    render(<CredentialsForm mode="sign-up" />)

    await fillAndSubmit(user, /create account/i)

    expect(auth.signUp).toHaveBeenCalledWith({
      email: "priya@example.com",
      password: "hunter2-hunter2",
      options: { emailRedirectTo: `${window.location.origin}/sign-in` },
    })
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/onboarding")
    )
    expect(router.refresh).toHaveBeenCalled()
  })

  it("asks the user to confirm their email when no session comes back", async () => {
    const user = userEvent.setup()
    auth.signUp.mockResolvedValue({
      data: { session: null, user: {} },
      error: null,
    })
    render(<CredentialsForm mode="sign-up" />)

    await fillAndSubmit(user, /create account/i)

    const note = await screen.findByRole("status")
    expect(note.textContent).toContain("priya@example.com")
    expect(note.textContent).toMatch(/confirm/i)
    expect(router.replace).not.toHaveBeenCalled()
    expect(screen.queryByLabelText("Password")).toBeNull()
  })

  it("points an existing account to sign-in", async () => {
    const user = userEvent.setup()
    auth.signUp.mockResolvedValue({
      data: { session: null, user: null },
      error: {
        code: "user_already_exists",
        name: "AuthApiError",
        message: "User already registered",
      },
    })
    render(<CredentialsForm mode="sign-up" />)

    await fillAndSubmit(user, /create account/i)

    expect((await screen.findByRole("alert")).textContent).toMatch(
      /already has an account/i
    )
  })

  it("links to sign-in", () => {
    render(<CredentialsForm mode="sign-up" />)

    expect(
      screen.getByRole("link", { name: /^sign in$/i }).getAttribute("href")
    ).toBe("/sign-in")
  })
})

import { expect, type Locator, type Page } from "@playwright/test"

/** Signs in on the real form and waits for the role's home screen. */
export async function signIn(
  page: Page,
  email: string,
  password: string,
  home: string
) {
  await page.goto("/sign-in")

  const emailField = page.getByLabel("Email", { exact: true })
  await whenHydrated(emailField)
  await emailField.fill(email)
  await page.getByLabel("Password", { exact: true }).fill(password)
  await page.getByRole("button", { name: "Sign in", exact: true }).click()

  await page.waitForURL(`**${home}`)
}

/**
 * Types a command into the Voice Dock and sends it. The dock keeps the text box once it
 * is chosen, and the box is disabled while a command is routed, so back-to-back
 * commands queue behind each other.
 */
export async function say(page: Page, command: string) {
  const dock = page.getByRole("group", { name: "Voice commands" })
  const input = dock.getByRole("textbox", { name: "Type a command" })

  if (!(await input.isVisible())) {
    await dock.getByRole("button", { name: "Type a command instead" }).click()
  }
  await input.fill(command)
  await input.press("Enter")
}

/**
 * Waits until React has attached to an element. A controlled input that is typed into
 * sooner is reset to empty when the page hydrates, which loses the text.
 */
export async function whenHydrated(element: Locator) {
  await expect
    .poll(() =>
      element.evaluate((node) =>
        Object.keys(node).some((key) => key.startsWith("__reactProps$"))
      )
    )
    .toBe(true)
}

/** The two seeded demo logins the smoke specs sign in with. */
export type DemoRole = "brand" | "creator"

const DEMO_HOME: Record<DemoRole, string> = {
  brand: "/brand/discover",
  creator: "/creator/packages",
}

/**
 * Signs in as the demo brand (Lumen Audio, `DEMO_BRAND_EMAIL`) or the demo creator
 * (Priya, `DEMO_HELPER_EMAIL`), both with `DEMO_PASSWORD`, and waits for that role's
 * home screen.
 */
export async function signInAs(page: Page, role: DemoRole) {
  const email =
    role === "brand"
      ? process.env.DEMO_BRAND_EMAIL
      : process.env.DEMO_HELPER_EMAIL
  const password = process.env.DEMO_PASSWORD
  if (!email || !password) {
    throw new Error(
      "Set DEMO_BRAND_EMAIL, DEMO_HELPER_EMAIL and DEMO_PASSWORD (in the shell or frontend/.env.e2e)."
    )
  }
  await signIn(page, email, password, DEMO_HOME[role])
}

/**
 * Steps a Stepper (the `group` that holds its minus and plus buttons) to `target`, one
 * click at a time. `noun` is the Stepper's own noun: "videos" for "Increase videos".
 */
export async function stepTo(group: Locator, noun: string, target: number) {
  const output = group.locator("output")
  for (let step = 0; step < 60; step++) {
    const current = Number.parseInt((await output.innerText()).trim(), 10)
    if (current === target) return
    const up = Number.isNaN(current) || current < target
    await group
      .getByRole("button", { name: `${up ? "Increase" : "Decrease"} ${noun}` })
      .click()
    // Wait for the click to land before reading again.
    if (!Number.isNaN(current)) {
      await expect(output).toHaveText(String(current + (up ? 1 : -1)))
    }
  }
  throw new Error(`Could not step "${noun}" to ${target}.`)
}

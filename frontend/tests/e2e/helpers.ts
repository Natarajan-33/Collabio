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

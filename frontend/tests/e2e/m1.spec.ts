import { expect, test } from "@playwright/test"

import { say, signIn, whenHydrated } from "./helpers"

/**
 * M1 smoke: the voice flows, driven through the Voice Dock's text box. Typing takes the
 * same road as speaking (`POST /api/v1/voice/command`, then the page acts on the intent),
 * so this covers everything except the microphone itself, which a person checks by hand.
 *
 * Needs the stack running (see playwright.config.ts) and the demo accounts seeded
 * (`uv run python -m scripts.seed --reset` in backend/). Their logins come from the
 * environment: DEMO_BRAND_EMAIL, DEMO_HELPER_EMAIL (Priya) and DEMO_PASSWORD.
 */

const demo = {
  brand: process.env.DEMO_BRAND_EMAIL ?? "",
  creator: process.env.DEMO_HELPER_EMAIL ?? "",
  password: process.env.DEMO_PASSWORD ?? "",
}

const DISCOVER = "/brand/discover"
const PACKAGES = "/creator/packages"

const SEARCH_COMMAND =
  "tech creators doing short-form reviews under two thousand dollars"
const PACKAGE_COMMAND =
  "short videos, tech, two per contract for nine hundred, extra video three fifty, email first"

test.describe("M1 smoke", () => {
  test.skip(
    !demo.brand || !demo.creator || !demo.password,
    "Set DEMO_BRAND_EMAIL, DEMO_HELPER_EMAIL and DEMO_PASSWORD (in the shell or frontend/.env.e2e) to run the M1 smoke spec."
  )

  test("brand discovers and reviews by typed command", async ({ page }) => {
    await signIn(page, demo.brand, demo.password, DISCOVER)

    // The unfiltered grid first, so every later change is the command's doing.
    const picks = page.getByRole("checkbox", { name: /^Select / })
    await expect(picks.first()).toBeAttached()

    await say(page, SEARCH_COMMAND)

    const filters = page.getByRole("group", { name: "Search filters" })
    for (const chip of ["Consumer tech", "Short video", "≤ $2,000"]) {
      await expect(filters.getByText(chip, { exact: true })).toBeVisible()
    }
    // The chips and the busy flag change together; wait for the results behind them.
    const results = page.getByRole("region", { name: "Creators", exact: true })
    await expect(results).toHaveAttribute("aria-busy", "false")
    await expect.poll(() => picks.count()).toBeGreaterThanOrEqual(10)

    await say(page, "select the top ten")

    const tray = page.getByRole("region", { name: "Selected creators" })
    await expect(tray).toContainText("10 selected")

    await tray.getByRole("link", { name: /^Review/ }).click()
    await page.waitForURL(`**${DISCOVER}/review`)

    // One column per creator, each with its own remove button.
    await expect(
      page.getByRole("button", { name: /^Remove .+ from the comparison$/ })
    ).toHaveCount(10)
  })

  test("creator drafts and publishes a package by typed command", async ({
    page,
  }) => {
    // Unique per run: the package stays in Priya's account (the seed's --reset removes it).
    const name = `E2E smoke ${Date.now()}`

    await signIn(page, demo.creator, demo.password, PACKAGES)
    await expect(
      page.getByRole("region", { name: "Your packages", exact: true })
    ).toBeVisible()

    await say(page, PACKAGE_COMMAND)

    const card = page.getByRole("region", { name: "Package draft" })
    await expect(card).toBeVisible()
    // $900 is the one figure only the dictation can have put there.
    await expect(card.locator('[data-slot="price"]')).toContainText("$900")

    // Everything but the name was dictated, so the name is all the card is waiting for.
    await card.getByLabel("Name", { exact: true }).fill(name)
    const publish = card.getByRole("button", { name: "Publish", exact: true })
    await expect(publish).toBeEnabled()
    await publish.click()

    const published = page.getByRole("group", { name, exact: true })
    await expect(
      published.getByText("Published", { exact: true })
    ).toBeVisible()
  })

  test("brand cannot open creator routes", async ({ page }) => {
    await signIn(page, demo.brand, demo.password, DISCOVER)

    await page.goto(PACKAGES)

    await page.waitForURL(`**${DISCOVER}`)
    await expect(page).not.toHaveURL(/\/creator/)
  })
})

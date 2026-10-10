import { expect, test } from "@playwright/test"

import { say, signIn } from "./helpers"

/**
 * M2 smoke: brief → launch → board for fictional @example.com creators only (no Resend
 * calls, no phone). Needs the stack with WORKERS_ENABLED=1 and a Gemini key.
 */

const demo = {
  brand: process.env.DEMO_BRAND_EMAIL ?? "",
  password: process.env.DEMO_PASSWORD ?? "",
}

const DISCOVER = "/brand/discover"

test.describe("M2 smoke", () => {
  test.skip(
    !demo.brand || !demo.password,
    "Set DEMO_BRAND_EMAIL and DEMO_PASSWORD to run the M2 smoke spec."
  )

  test("brand completes a brief, launches, and sees sent cards", async ({
    page,
  }) => {
    await signIn(page, demo.brand, demo.password, DISCOVER)

    await say(page, "beauty creators")
    await say(page, "select the top three")

    await page.getByRole("link", { name: /^Review/ }).click()
    await page.waitForURL("**/brand/discover/review")

    await page.getByRole("button", { name: "Start negotiation" }).click()
    await page.waitForURL("**/brand/briefs/**")

    const goLive = new Date()
    goLive.setUTCDate(goLive.getUTCDate() + 30)
    const iso = goLive.toISOString().slice(0, 10)

    await page.getByLabel("Deliverables").fill("2")
    await page.getByLabel("Format").click()
    await page.getByRole("option", { name: "Short video" }).click()
    await page.getByLabel("Go live by").fill(iso)
    await page.getByLabel("Opening ask").fill("800")
    await page.getByLabel("Budget ceiling (private)").fill("1000")
    await page
      .getByLabel("The ask")
      .fill("Two short reviews for the Lumen Pods launch")
    await page.getByLabel("Flexible on").click()
    await page.getByRole("option", { name: "Timeline" }).click()

    const launch = page.getByRole("button", { name: /^Launch to 3/ })
    await expect(launch).toBeEnabled()
    await launch.click()
    await page.waitForURL("**/brand/batches/**")

    await expect
      .poll(
        async () => {
          const sent = page.getByText("Sent", { exact: true })
          const testAddr = page.getByText("Not delivered: test address")
          return (await sent.count()) >= 3 && (await testAddr.count()) >= 3
        },
        { timeout: 90_000 }
      )
      .toBe(true)

    await page.getByText("Sent", { exact: true }).first().click()
    await expect(page.getByText("Email written")).toBeVisible()
    await expect(page.getByText("Email sent")).toBeVisible()
  })
})

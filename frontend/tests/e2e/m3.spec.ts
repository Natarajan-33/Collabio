import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test"

import { signInAs, stepTo } from "./helpers"

/**
 * M3 smoke: the whole deal loop between two browsers. The demo brand (Lumen Audio)
 * briefs Priya and Maya, Priya counters, the brand counters back, Priya accepts, and the
 * brand awards her with a payment schedule and declines the rest.
 *
 * Needs the stack running with WORKERS_ENABLED=1 and DEMO_MODE=1 on the backend (Maya is
 * unregistered, and Discover hides unregistered creators otherwise), a Gemini key, and
 * the demo accounts freshly seeded (`uv run python -m scripts.seed --reset` in backend/),
 * so Priya has no older Lumen Audio offers. Logins come from the environment:
 * DEMO_BRAND_EMAIL, DEMO_HELPER_EMAIL (Priya) and DEMO_PASSWORD.
 *
 * Priya is launched by email, so the app mails her the offer and, as the loop moves,
 * mails the demo inboxes. Maya has an @example.com address, which is never emailed. The
 * test asserts on the app, not on any inbox.
 */

const demo = {
  brand: process.env.DEMO_BRAND_EMAIL ?? "",
  creator: process.env.DEMO_HELPER_EMAIL ?? "",
  password: process.env.DEMO_PASSWORD ?? "",
}

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000"
const PRIYA = "Priya Raman"
const MAYA = "Maya Chen"

/** Emails go out through a worker and Gemini writes them: the first card takes a while. */
const SENT_TIMEOUT = 90_000
/** A change made on the other side arrives by the realtime doorbell. */
const DOORBELL_TIMEOUT = 45_000

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/** A signed-in browser of its own, set up like the ones the config gives a test. */
async function newSession(
  browser: Browser,
  role: "brand" | "creator"
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({
    baseURL: BASE_URL,
    reducedMotion: "reduce",
  })
  const page = await context.newPage()
  await signInAs(page, role)
  return { context, page }
}

/** One creator's card on the launch board. */
function card(board: Page, name: string): Locator {
  return board.locator("article").filter({ hasText: name })
}

/** A row of the offer desk's comparison table, by its heading ("Price"). */
function deskRow(desk: Page, label: string): Locator {
  return (
    desk
      .locator('[data-slot="compare-columns"]')
      .getByRole("row")
      // A row whose figure moved also reads "(changed)" to a screen reader.
      .filter({
        has: desk.getByRole("cell", {
          name: new RegExp("^" + escapeRegExp(label) + "(\\s*\\(changed\\))?$"),
        }),
      })
  )
}

/** What the desk's comparison table shows in one column of one row. */
async function deskCell(
  desk: Page,
  row: string,
  column: string
): Promise<string> {
  const table = desk.locator('[data-slot="compare-columns"]')
  const headings = await table.getByRole("columnheader").allInnerTexts()
  const index = headings.findIndex((text) => text.trim() === column)
  if (index < 0) return ""
  return (
    await deskRow(desk, row).getByRole("cell").nth(index).innerText()
  ).trim()
}

/** Edits one field of the brief in place: its pencil, the new value, Save. */
async function editBrief(
  page: Page,
  key: string,
  label: string,
  change: (row: Locator) => Promise<void>
) {
  const row = page.locator(`li[data-field="${key}"]`)
  await row.getByRole("button", { name: `Edit ${label}`, exact: true }).click()
  await change(row)
  await row.getByRole("button", { name: "Save", exact: true }).click()
  // Back to a plain row once it has saved.
  await expect(
    row.getByRole("button", { name: `Edit ${label}`, exact: true })
  ).toBeVisible()
}

/** Types into a brief field's one text, money or date input. */
function typeInto(value: string) {
  return async (row: Locator) => {
    await row.locator("input").first().fill(value)
  }
}

test.describe("M3 smoke", () => {
  test.skip(
    !demo.brand || !demo.creator || !demo.password,
    "Set DEMO_BRAND_EMAIL, DEMO_HELPER_EMAIL and DEMO_PASSWORD (in the shell or frontend/.env.e2e) to run the M3 smoke spec."
  )

  test("a brief becomes a booked deal: counter, counter, accept, award", async ({
    browser,
  }) => {
    test.setTimeout(300_000)

    const brandSession = await newSession(browser, "brand")
    const creatorSession = await newSession(browser, "creator")
    const brand = brandSession.page
    const priya = creatorSession.page

    try {
      // 1. Brand: a brief for Priya and Maya, one hire, launched.
      const picks = brand.getByRole("checkbox", { name: /^Select / })
      await expect(picks.first()).toBeAttached()
      await expect(
        brand.getByRole("region", { name: "Creators", exact: true })
      ).toHaveAttribute("aria-busy", "false")

      for (const name of [PRIYA, MAYA]) {
        const pick = brand.getByRole("checkbox", { name: `Select ${name}` })
        await expect(
          pick,
          `${name} is not on Discover. Is the backend running with DEMO_MODE=1 and the marketplace seeded?`
        ).toBeAttached()
        await pick.check()
      }
      const tray = brand.getByRole("region", { name: "Selected creators" })
      await expect(tray).toContainText("2 selected")

      await tray.getByRole("link", { name: /^Review/ }).click()
      await brand.waitForURL("**/brand/discover/review")
      await brand.getByRole("button", { name: "Start negotiation" }).click()
      await brand.waitForURL("**/brand/briefs/**")

      const goLive = new Date()
      goLive.setUTCDate(goLive.getUTCDate() + 30)
      const goLiveBy = goLive.toISOString().slice(0, 10)

      await expect(
        brand.getByRole("heading", { name: "Your brief" })
      ).toBeVisible()
      await editBrief(brand, "deliverables_count", "Deliverables", (row) =>
        stepTo(
          row.getByRole("group", { name: "Deliverables" }),
          "deliverables",
          3
        )
      )
      await editBrief(brand, "deliverables_format", "Format", async (row) => {
        await row.locator("select").selectOption({ label: "Short video" })
      })
      await editBrief(brand, "go_live_by", "Go live by", typeInto(goLiveBy))
      await editBrief(brand, "ask_price_cents", "Opening ask", typeInto("1000"))
      await editBrief(
        brand,
        "budget_ceiling_cents",
        "Budget ceiling (private)",
        typeInto("1500")
      )
      await editBrief(
        brand,
        "negotiation_ask",
        "The ask",
        typeInto("Three short reviews for the Lumen Pods launch")
      )
      await editBrief(brand, "flexibility", "Flexible on", async (row) => {
        await row.getByRole("button", { name: "Timeline", exact: true }).click()
      })

      // One hire; the board reports when it is reached.
      await stepTo(
        brand.getByRole("group", { name: "Creators to hire" }),
        "creators to hire",
        1
      )

      const launch = brand.getByRole("button", { name: "Launch to 2" })
      await expect(launch).toBeEnabled()
      await launch.click()
      await brand.waitForURL("**/brand/batches/**")

      const priyaCard = card(brand, PRIYA)
      const mayaCard = card(brand, MAYA)
      await expect(priyaCard.getByText("Sent", { exact: true })).toBeVisible({
        timeout: SENT_TIMEOUT,
      })
      await expect(mayaCard.getByText("Sent", { exact: true })).toBeVisible({
        timeout: SENT_TIMEOUT,
      })

      // 2. Priya: the offer is under Needs you; counter 3 videos for $1,200.
      await priya.goto("/creator/offers")
      await expect(
        priya.getByRole("tab", { name: /^Needs you/, selected: true })
      ).toBeVisible()
      // Exactly one Lumen Audio offer for Lumen Pods: an older one means the database
      // was not freshly seeded.
      const offer = priya.getByRole("link", { name: /Lumen Audio.*Lumen Pods/ })
      await expect(offer).toHaveCount(1, { timeout: DOORBELL_TIMEOUT })
      await offer.click()
      await priya.waitForURL("**/creator/offers/**")
      await expect(
        priya.getByRole("heading", { name: "Lumen Audio" })
      ).toBeVisible()

      await priya.getByRole("button", { name: "Counter", exact: true }).click()
      const priyaCounter = priya.getByRole("dialog", {
        name: "Counter this offer",
      })
      await stepTo(
        priyaCounter.getByRole("group", { name: "Videos", exact: true }),
        "videos",
        3
      )
      await priyaCounter.getByLabel("Price", { exact: true }).fill("1200")
      await priyaCounter
        .getByRole("button", { name: "Send counter", exact: true })
        .click()
      // $1,200 may sit under Priya's own floor for three videos; if so the dialog asks
      // once more before sending it.
      const belowFloor = priyaCounter.getByRole("button", {
        name: "Send below my floor",
      })
      await expect
        .poll(async () => {
          if (await belowFloor.isVisible()) {
            await belowFloor.click()
            return "sent"
          }
          return (await priyaCounter.isVisible()) ? "open" : "sent"
        })
        .toBe("sent")
      await expect(
        priya.getByText("Countered", { exact: true }).first()
      ).toBeVisible()

      // 3. Brand: Priya's card turns Countered; counter $1,100 with a note.
      await expect(
        priyaCard.getByText("Countered", { exact: true })
      ).toBeVisible({
        timeout: DOORBELL_TIMEOUT,
      })
      await expect(priyaCard).toContainText("$1,200")
      await priyaCard.getByText(PRIYA, { exact: true }).click()
      await brand.getByRole("button", { name: "Counter", exact: true }).click()
      const brandCounter = brand.getByRole("dialog", {
        name: `Counter ${PRIYA}`,
      })
      await stepTo(
        brandCounter.getByRole("group", { name: "Videos", exact: true }),
        "videos",
        3
      )
      await brandCounter.getByLabel("Price", { exact: true }).fill("1100")
      await brandCounter
        .getByLabel("Note", { exact: true })
        .fill("Can we meet here?")
      await brandCounter
        .getByRole("button", { name: "Send counter", exact: true })
        .click()
      await expect(brandCounter).toBeHidden()
      // Close the drawer: it is opened afresh for the award.
      await brand.keyboard.press("Escape")
      await expect(
        brand.getByRole("button", { name: "Counter", exact: true })
      ).toBeHidden()

      // 4. Priya: the desk shows the note and their ask of $1,100; accept.
      await expect(priya.locator('[data-slot="brand-note"]')).toContainText(
        "Can we meet here?",
        { timeout: DOORBELL_TIMEOUT }
      )
      await expect
        .poll(() => deskCell(priya, "Price", "Their ask"))
        .toBe("$1,100")

      await priya.getByRole("button", { name: "Accept", exact: true }).click()
      await priya.getByRole("button", { name: "Accept these terms" }).click()
      await expect(
        priya.getByText("Accepted", { exact: true }).first()
      ).toBeVisible()

      // 5. Brand: award with a 500 / 300 / 300 schedule, declining the remaining one.
      await expect(
        priyaCard.getByText("Accepted", { exact: true })
      ).toBeVisible({
        timeout: DOORBELL_TIMEOUT,
      })
      await priyaCard.getByText(PRIYA, { exact: true }).click()
      await brand.getByRole("button", { name: "Award", exact: true }).click()
      const award = brand.getByRole("dialog", { name: `Award ${PRIYA}` })
      await expect(award.getByLabel("Video 1 payment")).toBeVisible()
      await award.getByLabel("Video 1 payment").fill("500")
      await award.getByLabel("Video 2 payment").fill("300")
      await award.getByLabel("Video 3 payment").fill("300")
      await expect(award.getByTestId("milestone-total")).toHaveText(
        /Total\s*\$1,100\s*of\s*\$1,100/
      )
      await expect(
        award.getByRole("checkbox", {
          name: /Politely decline the remaining 1/,
        })
      ).toBeChecked()
      await award.getByRole("button", { name: "Confirm award" }).click()
      await expect(award).toBeHidden()

      // 6. Both: Priya is booked, the deal lists three payments and the brand's email,
      // the brand's Deals page lists it, and Maya's card is closed.
      await expect(priyaCard.getByText("Booked", { exact: true })).toBeVisible()
      await expect(mayaCard.getByText("Closed", { exact: true })).toBeVisible()

      await expect(priya.getByText("This offer is booked.")).toBeVisible({
        timeout: DOORBELL_TIMEOUT,
      })
      await priya.getByRole("link", { name: "View deal" }).click()
      await priya.waitForURL("**/creator/deals/**")
      await expect(priya.getByRole("table").locator("tbody tr")).toHaveCount(3)
      await expect(priya.getByRole("table")).toContainText("$500")
      await expect(
        priya.getByRole("link", {
          name: new RegExp(`^${escapeRegExp(demo.brand)}$`, "i"),
        })
      ).toBeVisible()

      await brand.goto("/brand/deals")
      const dealRow = brand
        .locator('[data-slot="deal-row"]')
        .filter({ hasText: PRIYA })
        .first()
      await expect(dealRow).toBeVisible()
      await expect(dealRow).toContainText("3 videos")
      await expect(dealRow).toContainText("$1,100")
    } finally {
      await brandSession.context.close()
      await creatorSession.context.close()
    }
  })
})

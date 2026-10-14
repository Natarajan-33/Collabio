import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { DealSummary } from "@/components/deal/deal-summary"
import { MilestoneEditor } from "@/components/deal/milestone-editor"
import type { components } from "@/lib/api/schema"

afterEach(cleanup)

type AgreedTerms = components["schemas"]["AgreedTerms"]
type MilestoneDraft = components["schemas"]["MilestoneDraft"]
type DealView = components["schemas"]["DealView"]

const AGREED: AgreedTerms = {
  videos: 3,
  format: "short_video",
  price_cents: 110000,
  go_live_by: "2026-11-30",
  conditions: ["No exclusivity"],
  addons: [],
}

const GOOD: MilestoneDraft[] = [
  { seq: 1, title: "Video 1", amount_cents: 50000, due_date: "2026-11-30" },
  { seq: 2, title: "Video 2", amount_cents: 30000, due_date: "2026-12-07" },
  { seq: 3, title: "Video 3", amount_cents: 30000, due_date: "2026-12-14" },
]

describe("MilestoneEditor", () => {
  it("shows one row per milestone and the running total", () => {
    render(<MilestoneEditor agreed={AGREED} value={GOOD} onChange={vi.fn()} />)
    expect(screen.getAllByRole("listitem")).toHaveLength(3)
    expect(screen.getByTestId("milestone-total").textContent).toContain(
      "$1,100 of $1,100"
    )
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("explains a total that does not match the price", () => {
    const value = [{ ...GOOD[0], amount_cents: 40000 }, GOOD[1], GOOD[2]]
    render(<MilestoneEditor agreed={AGREED} value={value} onChange={vi.fn()} />)
    expect(
      screen.getByText("Payments add up to $1,000, not the agreed $1,100")
    ).toBeTruthy()
    expect(screen.getByTestId("milestone-total").textContent).toContain(
      "$1,000 of $1,100"
    )
  })

  it("lists the other problems from the shared checks", () => {
    const value = [GOOD[0], { ...GOOD[1], due_date: "2026-11-29" }, GOOD[2]]
    render(<MilestoneEditor agreed={AGREED} value={value} onChange={vi.fn()} />)
    expect(
      screen.getByText(
        "Video 2 is due before the agreed go-live date Nov 30, 2026"
      )
    ).toBeTruthy()
  })

  it("emits the edited row only, with the amount in cents", async () => {
    const onChange = vi.fn()
    render(<MilestoneEditor agreed={AGREED} value={GOOD} onChange={onChange} />)
    const amount = screen.getByLabelText("Video 1 payment")
    await userEvent.clear(amount)
    await userEvent.type(amount, "400")
    expect(onChange).toHaveBeenLastCalledWith([
      { ...GOOD[0], amount_cents: 40000 },
      GOOD[1],
      GOOD[2],
    ])
  })

  it("edits a title and a due date", () => {
    const onChange = vi.fn()
    render(<MilestoneEditor agreed={AGREED} value={GOOD} onChange={onChange} />)
    fireEvent.change(screen.getByLabelText("Video 2 title"), {
      target: { value: "Intro cut" },
    })
    expect(onChange).toHaveBeenLastCalledWith([
      GOOD[0],
      { ...GOOD[1], title: "Intro cut" },
      GOOD[2],
    ])
    fireEvent.change(screen.getByLabelText("Video 3 due date"), {
      target: { value: "2026-12-20" },
    })
    expect(onChange).toHaveBeenLastCalledWith([
      GOOD[0],
      GOOD[1],
      { ...GOOD[2], due_date: "2026-12-20" },
    ])
  })

  it("has no way to add or remove a row", () => {
    render(<MilestoneEditor agreed={AGREED} value={GOOD} onChange={vi.fn()} />)
    expect(screen.queryByRole("button")).toBeNull()
  })

  it("reports a wrong row count alone", () => {
    render(
      <MilestoneEditor
        agreed={AGREED}
        value={GOOD.slice(0, 2)}
        onChange={vi.fn()}
      />
    )
    expect(
      screen.getByText("Expected 3 milestones, one per video")
    ).toBeTruthy()
    expect(screen.getAllByRole("alert")[0].querySelectorAll("li")).toHaveLength(
      1
    )
  })
})

describe("DealSummary", () => {
  const deal: DealView = {
    id: "d1",
    thread_id: "t1",
    batch_id: "b1",
    status: "booked",
    product_name: "Lumen Lamp",
    terms: AGREED,
    milestones: GOOD.map((m, i) => ({
      ...m,
      id: `m${i}`,
      status: "pending" as const,
    })),
    brand: { name: "Lumen", email: "hello@lumen.test" },
    creator: { name: "Priya Nair", email: "priya@example.test" },
    creator_handle: "priya",
    created_at: "2026-10-14T10:00:00Z",
  }

  it("shows the terms and the payment schedule", () => {
    render(<DealSummary deal={deal} viewer="brand" />)
    expect(
      screen.getByText("3 videos · $1,100 · live by Nov 30, 2026")
    ).toBeTruthy()
    expect(screen.getByText("No exclusivity")).toBeTruthy()
    expect(screen.getByText("Payment schedule")).toBeTruthy()
    expect(screen.getAllByRole("row")).toHaveLength(1 + 3 + 1)
    expect(screen.getByText("Dec 7, 2026")).toBeTruthy()
  })

  it("gives the brand the creator's name and a mailto link", () => {
    render(<DealSummary deal={deal} viewer="brand" />)
    expect(screen.getByText("Priya Nair")).toBeTruthy()
    expect(
      screen
        .getByRole("link", { name: "priya@example.test" })
        .getAttribute("href")
    ).toBe("mailto:priya@example.test")
    expect(screen.queryByText("Lumen")).toBeNull()
  })

  it("gives the creator the brand's name and a mailto link", () => {
    render(<DealSummary deal={deal} viewer="creator" />)
    expect(screen.getByText("Lumen")).toBeTruthy()
    expect(
      screen
        .getByRole("link", { name: "hello@lumen.test" })
        .getAttribute("href")
    ).toBe("mailto:hello@lumen.test")
    expect(screen.queryByText("priya@example.test")).toBeNull()
  })

  it("names the counterpart without a link when there is no address", () => {
    render(
      <DealSummary
        deal={{ ...deal, creator: { name: "Priya Nair", email: null } }}
        viewer="brand"
      />
    )
    expect(screen.getByText("Priya Nair")).toBeTruthy()
    expect(screen.queryByRole("link")).toBeNull()
  })
})

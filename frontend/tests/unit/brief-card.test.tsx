import { act, cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { BriefCard } from "@/components/brief/brief-card"
import type { components } from "@/lib/api/schema"
import type { BriefFieldKey } from "@/lib/brief/state"

type DealBrief = components["schemas"]["DealBrief"]

function brief(over: Partial<DealBrief> = {}): DealBrief {
  return {
    id: "brief-1",
    status: "draft",
    creator_ids: [],
    approved_at: null,
    batch_id: null,
    missing: [],
    violations: [],
    brand_name: "Lumen",
    product_name: "Lumen Lamp",
    product_summary: "A desk lamp that follows the sun.",
    deliverables_count: 3,
    deliverables_format: "short_video",
    budget_ceiling_cents: 200000,
    negotiation_ask: "Three videos, one mention each.",
    flexibility: ["price"],
    contact_email: "hello@lumen.test",
    ...over,
  }
}

const NONE: ReadonlySet<BriefFieldKey> = new Set()
const saved = () => vi.fn(async () => null as string | null)

function row(key: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-field="${key}"]`)
  if (!el) throw new Error(`no row for ${key}`)
  return el
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("BriefCard rows", () => {
  it("shows missing fields with the pulse utility and filled ones plainly", () => {
    render(<BriefCard brief={brief()} changed={NONE} onEdit={saved()} />)

    // Go-live and the opening ask are required and empty; the video length is optional.
    for (const key of ["go_live_by", "ask_price_cents"]) {
      expect(row(key).className).toContain("voice-missing")
      expect(row(key).dataset.state).toBe("missing")
    }
    expect(row("brand_name").className).not.toContain("voice-missing")
    expect(row("brand_name").dataset.state).toBe("filled")
    expect(row("deliverable_length_s").className).not.toContain("voice-missing")
    expect(
      within(row("deliverables_count")).getByText("3 short videos")
    ).toBeTruthy()
    expect(within(row("go_live_by")).getByText("—")).toBeTruthy()
  })

  it("keeps prices and counts in the number style", () => {
    render(
      <BriefCard
        brief={brief({ ask_price_cents: 90000 })}
        changed={NONE}
        onEdit={saved()}
      />
    )

    expect(
      within(row("ask_price_cents")).getByText("$900").className
    ).toContain("num")
    expect(
      within(row("deliverables_count")).getByText("3 short videos").className
    ).toContain("num")
  })

  it("flashes the fields that just changed", () => {
    vi.useFakeTimers()
    const changed = new Set<BriefFieldKey>(["ask_price_cents"])
    render(
      <BriefCard
        brief={brief({ ask_price_cents: 90000 })}
        changed={changed}
        onEdit={saved()}
      />
    )

    expect(row("ask_price_cents").dataset.state).toBe("changed")
    act(() => {
      vi.advanceTimersByTime(1199)
    })
    expect(row("ask_price_cents").dataset.state).toBe("changed")
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(row("ask_price_cents").dataset.state).toBe("filled")
  })

  it("flashes again when a new save changes the same field", () => {
    vi.useFakeTimers()
    const view = render(
      <BriefCard
        brief={brief({ ask_price_cents: 90000 })}
        changed={new Set<BriefFieldKey>(["ask_price_cents"])}
        onEdit={saved()}
      />
    )
    act(() => {
      vi.advanceTimersByTime(1200)
    })
    expect(row("ask_price_cents").dataset.state).toBe("filled")

    view.rerender(
      <BriefCard
        brief={brief({ ask_price_cents: 80000 })}
        changed={new Set<BriefFieldKey>(["ask_price_cents"])}
        onEdit={saved()}
      />
    )
    expect(row("ask_price_cents").dataset.state).toBe("changed")
  })

  it("labels the ceiling as private", () => {
    render(<BriefCard brief={brief()} changed={NONE} onEdit={saved()} />)

    const ceiling = row("budget_ceiling_cents")
    expect(within(ceiling).getByText("Budget ceiling (private)")).toBeTruthy()
    expect(
      within(ceiling).getByText("Only you can see this").className
    ).toContain("sr-only")
    expect(ceiling.querySelector("svg")).not.toBeNull()
    // Nothing else is private.
    expect(screen.getAllByText("Only you can see this")).toHaveLength(1)
  })

  it("shows a rule the brief breaks under its field", () => {
    render(
      <BriefCard
        brief={brief({
          ask_price_cents: 300000,
          violations: [
            {
              field: "ask_price_cents",
              message: "The opening ask can't be above the budget ceiling.",
            },
          ],
        })}
        changed={NONE}
        onEdit={saved()}
      />
    )

    expect(
      within(row("ask_price_cents")).getByText(
        "The opening ask can't be above the budget ceiling."
      )
    ).toBeTruthy()
  })
})

describe("BriefCard editing", () => {
  it("saves a money field in cents and closes the editor", async () => {
    const user = userEvent.setup()
    const onEdit = saved()
    render(<BriefCard brief={brief()} changed={NONE} onEdit={onEdit} />)

    await user.click(screen.getByRole("button", { name: "Edit Opening ask" }))
    await user.type(screen.getByLabelText("Opening ask"), "1,200.50")
    await user.click(screen.getByRole("button", { name: "Save" }))

    expect(onEdit).toHaveBeenCalledWith("ask_price_cents", {
      ask_price_cents: 120050,
    })
    expect(screen.queryByLabelText("Opening ask")).toBeNull()
  })

  it("shows a save error under the field and keeps the editor open", async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn(async () => "The go-live date must be in the future.")
    render(<BriefCard brief={brief()} changed={NONE} onEdit={onEdit} />)

    await user.click(screen.getByRole("button", { name: "Edit Go live by" }))
    await user.type(screen.getByLabelText("Go live by"), "2020-01-01")
    await user.click(screen.getByRole("button", { name: "Save" }))

    expect(onEdit).toHaveBeenCalledWith("go_live_by", {
      go_live_by: "2020-01-01",
    })
    const alert = await within(row("go_live_by")).findByRole("alert")
    expect(alert.textContent).toBe("The go-live date must be in the future.")
    expect(screen.getByLabelText("Go live by")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Save" })).toBeTruthy()
  })

  it("cancels without saving", async () => {
    const user = userEvent.setup()
    const onEdit = saved()
    render(<BriefCard brief={brief()} changed={NONE} onEdit={onEdit} />)

    await user.click(screen.getByRole("button", { name: "Edit Brand" }))
    await user.type(screen.getByLabelText("Brand"), " Co")
    await user.click(screen.getByRole("button", { name: "Cancel" }))

    expect(onEdit).not.toHaveBeenCalled()
    expect(within(row("brand_name")).getByText("Lumen")).toBeTruthy()
  })

  it("steps the deliverable count, never below one", async () => {
    const user = userEvent.setup()
    const onEdit = saved()
    render(
      <BriefCard
        brief={brief({ deliverables_count: 1 })}
        changed={NONE}
        onEdit={onEdit}
      />
    )

    await user.click(screen.getByRole("button", { name: "Edit Deliverables" }))
    expect(screen.getByRole("button", { name: /^Decrease/ })).toHaveProperty(
      "disabled",
      true
    )
    await user.click(screen.getByRole("button", { name: /^Increase/ }))
    await user.click(screen.getByRole("button", { name: "Save" }))

    expect(onEdit).toHaveBeenCalledWith("deliverables_count", {
      deliverables_count: 2,
    })
  })

  it("picks the format from a list", async () => {
    const user = userEvent.setup()
    const onEdit = saved()
    render(<BriefCard brief={brief()} changed={NONE} onEdit={onEdit} />)

    await user.click(screen.getByRole("button", { name: "Edit Format" }))
    await user.selectOptions(screen.getByLabelText("Format"), "story")
    await user.click(screen.getByRole("button", { name: "Save" }))

    expect(onEdit).toHaveBeenCalledWith("deliverables_format", {
      deliverables_format: "story",
    })
  })

  it("lets None replace the other flexibility, and another choice replace None", async () => {
    const user = userEvent.setup()
    const onEdit = saved()
    render(
      <BriefCard
        brief={brief({ flexibility: ["price", "timeline"] })}
        changed={NONE}
        onEdit={onEdit}
      />
    )
    const pressed = (name: string) =>
      screen.getByRole("button", { name }).getAttribute("aria-pressed")

    await user.click(screen.getByRole("button", { name: "Edit Flexible on" }))
    await user.click(screen.getByRole("button", { name: "None" }))
    expect(pressed("None")).toBe("true")
    expect(pressed("Price")).toBe("false")
    expect(pressed("Timeline")).toBe("false")

    await user.click(screen.getByRole("button", { name: "Deliverables" }))
    expect(pressed("None")).toBe("false")
    await user.click(screen.getByRole("button", { name: "Save" }))

    expect(onEdit).toHaveBeenCalledWith("flexibility", {
      flexibility: ["deliverables"],
    })
  })

  it("clears an optional field that was emptied", async () => {
    const user = userEvent.setup()
    const onEdit = saved()
    render(
      <BriefCard
        brief={brief({ deliverable_length_s: 45 })}
        changed={NONE}
        onEdit={onEdit}
      />
    )

    await user.click(screen.getByRole("button", { name: "Edit Video length" }))
    await user.clear(screen.getByLabelText("Video length"))
    await user.click(screen.getByRole("button", { name: "Save" }))

    expect(onEdit).toHaveBeenCalledWith("deliverable_length_s", {
      deliverable_length_s: null,
    })
  })
})

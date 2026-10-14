import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ExpiryBadge } from "@/components/deal/expiry-badge"
import { TermsCard } from "@/components/deal/terms-card"
import type { TermsDraft } from "@/lib/deal/terms"

afterEach(cleanup)

/** The box of warnings under the terms (the stepper's count is a status too). */
const warnings = () =>
  document.querySelector<HTMLElement>('[data-slot="terms-warnings"]')

const FULL: TermsDraft = {
  videos: 3,
  price_cents: 120000,
  go_live_by: "2026-11-30",
  conditions: ["No exclusivity"],
  note: null,
}

describe("TermsCard", () => {
  it("emits the price in cents as it is typed", async () => {
    const onChange = vi.fn()
    render(
      <TermsCard value={{ ...FULL, price_cents: null }} onChange={onChange} />
    )
    await userEvent.type(screen.getByLabelText("Price"), "1200")
    expect(onChange).toHaveBeenLastCalledWith({
      ...FULL,
      price_cents: 120000,
    })
  })

  it("steps the videos between 1 and 50", async () => {
    const onChange = vi.fn()
    const { rerender } = render(<TermsCard value={FULL} onChange={onChange} />)
    await userEvent.click(
      screen.getByRole("button", { name: "Increase videos" })
    )
    expect(onChange).toHaveBeenLastCalledWith({ ...FULL, videos: 4 })

    rerender(<TermsCard value={{ ...FULL, videos: 1 }} onChange={onChange} />)
    expect(
      screen
        .getByRole("button", { name: "Decrease videos" })
        .matches(":disabled")
    ).toBe(true)
    rerender(<TermsCard value={{ ...FULL, videos: 50 }} onChange={onChange} />)
    expect(
      screen
        .getByRole("button", { name: "Increase videos" })
        .matches(":disabled")
    ).toBe(true)
  })

  it("emits the go-live date, and null when it is cleared", () => {
    const onChange = vi.fn()
    render(<TermsCard value={FULL} onChange={onChange} />)
    const date = screen.getByLabelText("Go live by")
    fireEvent.change(date, { target: { value: "2026-12-05" } })
    expect(onChange).toHaveBeenLastCalledWith({
      ...FULL,
      go_live_by: "2026-12-05",
    })
    fireEvent.change(date, { target: { value: "" } })
    expect(onChange).toHaveBeenLastCalledWith({ ...FULL, go_live_by: null })
  })

  it("adds a condition once and removes one", async () => {
    const onChange = vi.fn()
    render(<TermsCard value={FULL} onChange={onChange} />)
    await userEvent.type(
      screen.getByLabelText("Add a condition"),
      "Usage 30 days{Enter}"
    )
    expect(onChange).toHaveBeenLastCalledWith({
      ...FULL,
      conditions: ["No exclusivity", "Usage 30 days"],
    })

    onChange.mockClear()
    await userEvent.type(
      screen.getByLabelText("Add a condition"),
      "no exclusivity{Enter}"
    )
    expect(onChange).not.toHaveBeenCalled()

    await userEvent.click(
      screen.getByRole("button", { name: "Remove condition No exclusivity" })
    )
    expect(onChange).toHaveBeenLastCalledWith({ ...FULL, conditions: [] })
  })

  it("shows the floor warning in dollars", () => {
    render(
      <TermsCard value={FULL} onChange={vi.fn()} floorWarningCents={10000} />
    )
    expect(warnings()?.textContent).toContain("That's $100 below your floor")
  })

  it("shows no warning without one, and shows a ceiling message as given", () => {
    const { rerender } = render(<TermsCard value={FULL} onChange={vi.fn()} />)
    expect(warnings()).toBeNull()
    rerender(
      <TermsCard
        value={FULL}
        onChange={vi.fn()}
        ceilingMessage="This is $200 over your ceiling"
      />
    )
    expect(warnings()?.textContent).toContain("This is $200 over your ceiling")
  })

  it("marks missing videos and price", () => {
    const { container } = render(
      <TermsCard value={{ conditions: [] }} onChange={vi.fn()} />
    )
    const missing = [...container.querySelectorAll("[data-missing]")].map(
      (el) => el.getAttribute("data-field")
    )
    expect(missing).toEqual(["videos", "price_cents"])
    expect(container.querySelectorAll(".voice-missing")).toHaveLength(2)
  })

  it("marks nothing missing when the terms are complete", () => {
    const { container } = render(<TermsCard value={FULL} onChange={vi.fn()} />)
    expect(container.querySelector("[data-missing]")).toBeNull()
  })

  it("offers the note only on request, up to 1000 characters", async () => {
    const onChange = vi.fn()
    const { rerender } = render(<TermsCard value={FULL} onChange={onChange} />)
    expect(screen.queryByLabelText("Note")).toBeNull()

    rerender(<TermsCard value={FULL} onChange={onChange} showNote />)
    const note = screen.getByLabelText("Note")
    expect(note.getAttribute("maxlength")).toBe("1000")
    await userEvent.type(note, "x")
    expect(onChange).toHaveBeenLastCalledWith({ ...FULL, note: "x" })
  })

  it("locks every control while disabled", () => {
    render(<TermsCard value={FULL} onChange={vi.fn()} showNote disabled />)
    expect(screen.getByLabelText("Price").matches(":disabled")).toBe(true)
    expect(screen.getByLabelText("Go live by").matches(":disabled")).toBe(true)
    expect(screen.getByLabelText("Note").matches(":disabled")).toBe(true)
    expect(
      screen
        .getByRole("button", { name: "Increase videos" })
        .matches(":disabled")
    ).toBe(true)
  })
})

describe("ExpiryBadge", () => {
  const now = new Date("2026-10-14T12:00:00Z")
  const at = (ms: number) => new Date(now.getTime() + ms).toISOString()
  const HOUR = 3_600_000

  it.each([
    [3 * 24 * HOUR + HOUR, "expires in 3d"],
    [24 * HOUR, "expires in 1d"],
    [5 * HOUR + 600_000, "expires in 5h"],
    [90_000, "expires in 1m"],
    [0, "expired"],
    [-HOUR, "expired"],
  ])("reads %i ms ahead as %s", (ahead, text) => {
    const { container } = render(
      <ExpiryBadge expiresAt={at(ahead)} now={now} />
    )
    expect(container.textContent).toContain(text)
  })

  it("renders nothing without an expiry", () => {
    const { container } = render(<ExpiryBadge expiresAt={null} now={now} />)
    expect(container.innerHTML).toBe("")
  })

  it("flags an offer with under a day left", () => {
    const { container } = render(
      <ExpiryBadge expiresAt={at(5 * HOUR)} now={now} />
    )
    expect(container.firstElementChild?.getAttribute("data-urgent")).toBe(
      "true"
    )
  })
})

import { cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { CompareColumns } from "@/components/deal/compare-columns"
import type { components } from "@/lib/api/schema"

afterEach(cleanup)

type TermsColumn = components["schemas"]["TermsColumn"]

const MINE: TermsColumn = {
  videos: 3,
  price_cents: 150000,
  per_video_cents: 50000,
  go_live_by: "2026-11-30",
  conditions: [],
}
const THEIRS: TermsColumn = {
  videos: 3,
  price_cents: 100000,
  per_video_cents: 33333,
  go_live_by: "2026-11-30",
  conditions: ["No exclusivity"],
}
const LATEST: TermsColumn = {
  videos: 3,
  price_cents: 120000,
  per_video_cents: 40000,
  go_live_by: "2026-12-05",
  conditions: ["No exclusivity", "Usage 30 days"],
}

const row = (name: string) =>
  screen.getByRole("row", { name: new RegExp(`^${name}`) })

describe("CompareColumns", () => {
  it("lays out the five rows under three headings", () => {
    render(
      <CompareColumns
        mine={MINE}
        theirs={THEIRS}
        latest={LATEST}
        changed={[]}
      />
    )
    for (const label of [
      "Videos",
      "Price",
      "\\$/video",
      "Go-live",
      "Conditions",
    ]) {
      expect(row(label)).toBeTruthy()
    }
    expect(
      screen.getAllByRole("columnheader").map((h) => h.textContent)
    ).toEqual(["Term", "My package", "Their ask", "Latest"])
  })

  it("shows prices per video and dates in words", () => {
    render(
      <CompareColumns
        mine={MINE}
        theirs={THEIRS}
        latest={LATEST}
        changed={[]}
      />
    )
    expect(within(row("Price")).getByText("$1,500")).toBeTruthy()
    expect(within(row("\\$/video")).getByText("$333.33")).toBeTruthy()
    expect(within(row("Go-live")).getByText("Dec 5, 2026")).toBeTruthy()
    expect(within(row("Conditions")).getByText("Usage 30 days")).toBeTruthy()
  })

  it("marks the changed rows", () => {
    render(
      <CompareColumns
        mine={MINE}
        theirs={THEIRS}
        latest={LATEST}
        changed={["price_cents", "go_live_by"]}
      />
    )
    expect(row("Price").getAttribute("data-changed")).toBe("true")
    expect(row("\\$/video").getAttribute("data-changed")).toBe("true")
    expect(row("Go-live").getAttribute("data-changed")).toBe("true")
    expect(row("Videos").getAttribute("data-changed")).toBeNull()
    expect(row("Conditions").getAttribute("data-changed")).toBeNull()
  })

  it("marks the conditions row when conditions changed", () => {
    render(
      <CompareColumns
        mine={MINE}
        theirs={THEIRS}
        latest={LATEST}
        changed={["conditions"]}
      />
    )
    expect(row("Conditions").getAttribute("data-changed")).toBe("true")
    expect(row("Price").getAttribute("data-changed")).toBeNull()
  })

  it("leaves out the columns that do not exist yet", () => {
    render(
      <CompareColumns mine={null} theirs={THEIRS} latest={null} changed={[]} />
    )
    expect(
      screen.getAllByRole("columnheader").map((h) => h.textContent)
    ).toEqual(["Term", "Their ask"])
  })

  it("dashes a missing figure and says no conditions", () => {
    render(
      <CompareColumns
        mine={null}
        theirs={{
          ...THEIRS,
          videos: null,
          price_cents: null,
          per_video_cents: null,
          go_live_by: null,
          conditions: [],
        }}
        latest={null}
        changed={[]}
      />
    )
    expect(within(row("Price")).getByText("—")).toBeTruthy()
    expect(within(row("Conditions")).getByText("None")).toBeTruthy()
  })

  it("takes its own column names", () => {
    render(
      <CompareColumns
        mine={MINE}
        theirs={THEIRS}
        latest={LATEST}
        changed={[]}
        labels={["Your package", "Your offer", "Their counter"]}
      />
    )
    expect(
      screen.getByRole("columnheader", { name: "Their counter" })
    ).toBeTruthy()
  })
})

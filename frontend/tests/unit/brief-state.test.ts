import { describe, expect, it } from "vitest"

import type { components } from "@/lib/api/schema"
import {
  BRIEF_FIELDS,
  changedFields,
  fieldState,
  formatFieldValue,
  invalidFieldMessage,
  launchLabel,
  MISSING_LABELS,
  missingLabels,
  type BriefFieldKey,
} from "@/lib/brief/state"

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
    flexibility: [],
    ...over,
  }
}

const NONE: ReadonlySet<BriefFieldKey> = new Set()

describe("BRIEF_FIELDS", () => {
  it("lists fields in the brief's order with exact labels", () => {
    expect(BRIEF_FIELDS.map((f) => [f.key, f.label])).toEqual([
      ["brand_name", "Brand"],
      ["product_name", "Product"],
      ["product_summary", "Product summary"],
      ["deliverables_count", "Deliverables"],
      ["deliverables_format", "Format"],
      ["deliverable_length_s", "Video length"],
      ["go_live_by", "Go live by"],
      ["budget_ceiling_cents", "Budget ceiling (private)"],
      ["ask_price_cents", "Opening ask"],
      ["negotiation_ask", "The ask"],
      ["flexibility", "Flexible on"],
      ["contact_email", "Reply-to contact"],
    ])
  })

  it("marks only the video length optional and only the ceiling private", () => {
    expect(BRIEF_FIELDS.filter((f) => !f.required).map((f) => f.key)).toEqual([
      "deliverable_length_s",
    ])
    expect(BRIEF_FIELDS.filter((f) => f.private).map((f) => f.key)).toEqual([
      "budget_ceiling_cents",
    ])
  })
})

describe("formatFieldValue", () => {
  it("formats values", () => {
    const b = brief({
      deliverables_count: 3,
      deliverables_format: "short_video",
      ask_price_cents: 120000,
      budget_ceiling_cents: 99950,
      go_live_by: "2026-11-14",
      flexibility: ["timeline", "price"],
      deliverable_length_s: 45,
      brand_name: "Lumen",
    })
    expect(formatFieldValue(b, "deliverables_count")).toBe("3 short videos")
    expect(formatFieldValue(b, "deliverables_format")).toBe("Short video")
    expect(formatFieldValue(b, "ask_price_cents")).toBe("$1,200")
    expect(formatFieldValue(b, "budget_ceiling_cents")).toBe("$999.50")
    expect(formatFieldValue(b, "go_live_by")).toBe("Nov 14, 2026")
    expect(formatFieldValue(b, "flexibility")).toBe("Timeline, Price")
    expect(formatFieldValue(b, "deliverable_length_s")).toBe("45 s")
    expect(formatFieldValue(b, "brand_name")).toBe("Lumen")
  })

  it("singularises one deliverable and names a count without a format", () => {
    expect(
      formatFieldValue(
        brief({ deliverables_count: 1, deliverables_format: "story" }),
        "deliverables_count"
      )
    ).toBe("1 story")
    expect(
      formatFieldValue(
        brief({ deliverables_count: 2, deliverables_format: "story" }),
        "deliverables_count"
      )
    ).toBe("2 stories")
    expect(
      formatFieldValue(brief({ deliverables_count: 4 }), "deliverables_count")
    ).toBe("4")
  })

  it("reads none as None and an empty field as a dash", () => {
    expect(
      formatFieldValue(brief({ flexibility: ["none"] }), "flexibility")
    ).toBe("None")
    expect(formatFieldValue(brief(), "flexibility")).toBe("—")
    expect(formatFieldValue(brief(), "ask_price_cents")).toBe("—")
    expect(formatFieldValue(brief({ brand_name: "  " }), "brand_name")).toBe(
      "—"
    )
    expect(formatFieldValue(brief(), "go_live_by")).toBe("—")
  })
})

describe("fieldState", () => {
  it("marks a required empty field missing and a just-saved one changed", () => {
    const b = brief({ brand_name: "Lumen" })
    expect(fieldState(b, "go_live_by", NONE)).toBe("missing")
    expect(fieldState(b, "flexibility", NONE)).toBe("missing")
    expect(fieldState(b, "brand_name", NONE)).toBe("filled")
    expect(fieldState(b, "brand_name", new Set(["brand_name"]))).toBe("changed")
  })

  it("never calls an empty optional field missing", () => {
    expect(fieldState(brief(), "deliverable_length_s", NONE)).toBe("filled")
  })

  it("treats a filled flexibility of none as filled", () => {
    expect(
      fieldState(brief({ flexibility: ["none"] }), "flexibility", NONE)
    ).toBe("filled")
  })
})

describe("changedFields", () => {
  it("finds the fields a save changed", () => {
    const before = brief({ ask_price_cents: 100000, flexibility: ["price"] })
    const after = brief({
      ask_price_cents: 90000,
      flexibility: ["price"],
      go_live_by: "2026-12-01",
    })
    expect([...changedFields(before, after)].sort()).toEqual([
      "ask_price_cents",
      "go_live_by",
    ])
  })

  it("compares flexibility by content, and ignores a save that changed nothing", () => {
    const a = brief({ flexibility: ["timeline", "price"] })
    expect(
      changedFields(a, brief({ flexibility: ["timeline", "price"] })).size
    ).toBe(0)
    expect([...changedFields(a, brief({ flexibility: ["timeline"] }))]).toEqual(
      ["flexibility"]
    )
  })

  it("flashes nothing on the first load", () => {
    expect(changedFields(null, brief({ brand_name: "Lumen" })).size).toBe(0)
  })
})

describe("launchLabel", () => {
  it("names how many creators the launch reaches", () => {
    expect(launchLabel(10)).toBe("Launch to 10")
    expect(launchLabel(1)).toBe("Launch to 1")
  })
})

describe("missing labels", () => {
  it("mirrors the backend wording, lower case", () => {
    expect(MISSING_LABELS.go_live_by).toBe("go-live date")
    expect(MISSING_LABELS.ask_price_cents).toBe("opening ask")
    expect(MISSING_LABELS.negotiation_ask).toBe("what to negotiate for")
    expect(missingLabels(["go_live_by", "ask_price_cents"])).toEqual([
      "go-live date",
      "opening ask",
    ])
  })

  it("passes an unknown key through", () => {
    expect(missingLabels(["mystery"])).toEqual(["mystery"])
  })
})

describe("invalidFieldMessage", () => {
  it("reads an invalid_field detail", () => {
    expect(
      invalidFieldMessage({
        error: "invalid_field",
        field: "go_live_by",
        message: "The go-live date must be in the future.",
      })
    ).toEqual({
      field: "go_live_by",
      message: "The go-live date must be in the future.",
    })
  })

  it("is null for anything else", () => {
    expect(invalidFieldMessage(undefined)).toBeNull()
    expect(invalidFieldMessage("brief_launched")).toBeNull()
    expect(invalidFieldMessage({ error: "brief_incomplete" })).toBeNull()
    expect(
      invalidFieldMessage({ error: "invalid_field", field: "x" })
    ).toBeNull()
  })
})

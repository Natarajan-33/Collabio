import { describe, expect, it } from "vitest"

import {
  REQUIRED_FIELDS,
  dollarsText,
  draftBody,
  draftFromPackage,
  draftViolations,
  completeDraft,
  emptyDraft,
  fieldLabel,
  missingFields,
  mergeViolations,
  parseDollars,
  rejectionFrom,
  sameDraft,
  type MyPackage,
  type PackageDraft,
} from "@/lib/packages/draft"

const COMPLETE: PackageDraft = {
  name: "Launch Duo",
  content_type: "short_video",
  niche: "consumer_tech",
  volume_count: 2,
  volume_basis: "per_contract",
  base_price_cents: 90000,
  preferred_channel: "email_first",
  included: [],
  freebies: [],
  addons: [{ name: "Extra video", price_cents: 35000, unit: "video" }],
  extras: [],
}

const NICHES = ["consumer_tech", "beauty"]

describe("completeDraft", () => {
  it("fills in the lists a partial draft leaves out", () => {
    expect(completeDraft({ volume_count: 2 })).toEqual({
      volume_count: 2,
      included: [],
      freebies: [],
      addons: [],
      extras: [],
    })
  })

  it("keeps the lists it has", () => {
    expect(completeDraft(COMPLETE).addons).toEqual(COMPLETE.addons)
  })
})

describe("missingFields", () => {
  it("lists every required field of an empty draft, in the order the editor asks", () => {
    expect(missingFields(emptyDraft())).toEqual([
      "name",
      "content_type",
      "niche",
      "volume_count",
      "volume_basis",
      "base_price_cents",
      "preferred_channel",
    ])
    expect(missingFields(emptyDraft())).toEqual([...REQUIRED_FIELDS])
  })

  it("is empty for a complete draft, with or without the optional fields", () => {
    expect(missingFields(COMPLETE)).toEqual([])
    expect(
      missingFields({
        ...COMPLETE,
        lead_time_days: null,
        slots_per_month: null,
      })
    ).toEqual([])
  })

  it("counts a blank name as missing, and a zero as present", () => {
    expect(missingFields({ ...COMPLETE, name: "   " })).toEqual(["name"])
    expect(missingFields({ ...COMPLETE, volume_count: 0 })).toEqual([])
  })
})

describe("draftViolations", () => {
  it("finds none in a complete draft", () => {
    expect(draftViolations(COMPLETE, NICHES)).toEqual([])
  })

  it("does not report a field that is only missing", () => {
    expect(draftViolations(emptyDraft(), NICHES)).toEqual([])
  })

  it("reports a niche that is not one of the creator's", () => {
    const [violation] = draftViolations(
      { ...COMPLETE, niche: "gaming" },
      NICHES
    )
    expect(violation.field).toBe("niche")
    expect(violation.message).toContain("Consumer tech")
    expect(violation.message).toContain("Beauty")
  })

  it("reports a count below one and a price of nothing", () => {
    const fields = draftViolations(
      { ...COMPLETE, volume_count: 0, base_price_cents: 0 },
      NICHES
    ).map((v) => v.field)
    expect(fields).toEqual(["volume_count", "base_price_cents"])
  })

  it("reports add-ons and extras that repeat a name or cost nothing", () => {
    const violations = draftViolations(
      {
        ...COMPLETE,
        addons: [
          { name: "Extra video", price_cents: 35000, unit: "video" },
          { name: " extra VIDEO ", price_cents: 0, unit: "video" },
        ],
        extras: [{ name: "Thumbnails", price_cents: 0 }],
      },
      NICHES
    )
    expect(violations.map((v) => v.field)).toEqual([
      "addons",
      "addons",
      "extras",
    ])
    expect(violations[0].message).toMatch(/different name/i)
    expect(violations[1].message).toMatch(/price above \$0/i)
  })

  it("reports an add-on with no name", () => {
    const violations = draftViolations(
      {
        ...COMPLETE,
        addons: [{ name: "  ", price_cents: 1000, unit: "item" }],
      },
      NICHES
    )
    expect(violations).toEqual([
      { field: "addons", message: "Name every add-on." },
    ])
  })

  it("reports negative slots and lead time", () => {
    const fields = draftViolations(
      { ...COMPLETE, slots_per_month: -1, lead_time_days: -2 },
      NICHES
    ).map((v) => v.field)
    expect(fields).toEqual(["slots_per_month", "lead_time_days"])
  })
})

describe("mergeViolations", () => {
  it("keeps one of each field and message", () => {
    const a = { field: "niche", message: "Pick one." }
    const b = { field: "name", message: "Name it." }
    expect(mergeViolations([a], [b, a])).toEqual([a, b])
  })
})

describe("parseDollars and dollarsText", () => {
  it("reads dollars as whole cents without floating point", () => {
    expect(parseDollars("900")).toBe(90000)
    expect(parseDollars("999.5")).toBe(99950)
    expect(parseDollars("999.50")).toBe(99950)
    expect(parseDollars("0.07")).toBe(7)
    expect(parseDollars("1.")).toBe(100)
    expect(parseDollars(".5")).toBe(50)
    expect(parseDollars("0")).toBe(0)
  })

  it("reads nothing as no amount", () => {
    expect(parseDollars("")).toBeNull()
    expect(parseDollars(" ")).toBeNull()
    expect(parseDollars(".")).toBeNull()
    expect(parseDollars("abc")).toBeNull()
  })

  it("writes cents as the text a person would type", () => {
    expect(dollarsText(90000)).toBe("900")
    expect(dollarsText(99950)).toBe("999.50")
    expect(dollarsText(7)).toBe("0.07")
    expect(dollarsText(null)).toBe("")
    expect(dollarsText(0)).toBe("")
  })
})

describe("draftFromPackage", () => {
  const saved: MyPackage = {
    id: "pkg-1",
    name: "Launch Duo",
    content_type: "short_video",
    niche: "consumer_tech",
    volume_count: 2,
    volume_basis: "per_contract",
    base_price_cents: 90000,
    per_video_cents: 45000,
    one_liner: "2 videos/contract · $900 · +1 video $350",
    lead_time_days: null,
    preferred_channel: "email_first",
    addons: [{ name: "Extra video", price_cents: 35000, unit: "video" }],
    status: "draft",
    floor_price_cents: 80000,
    currency: "USD",
    included: ["1 revision"],
    freebies: [],
    extras: [{ name: "Thumbnail pack", price_cents: 5000 }],
    slots_per_month: 4,
  }

  it("keeps the terms and leaves out what is not a term", () => {
    const draft = draftFromPackage(saved)
    expect(draft).toEqual({
      name: "Launch Duo",
      content_type: "short_video",
      niche: "consumer_tech",
      volume_count: 2,
      volume_basis: "per_contract",
      base_price_cents: 90000,
      currency: "USD",
      included: ["1 revision"],
      freebies: [],
      addons: [{ name: "Extra video", price_cents: 35000, unit: "video" }],
      extras: [{ name: "Thumbnail pack", price_cents: 5000 }],
      slots_per_month: 4,
      lead_time_days: null,
      preferred_channel: "email_first",
    })
    expect(missingFields(draft)).toEqual([])
  })
})

describe("draftBody", () => {
  it("trims words and sends optional fields as given", () => {
    const body = draftBody({
      ...COMPLETE,
      name: "  Launch Duo ",
      lead_time_days: null,
      included: [" 1 revision "],
      addons: [{ name: " Extra video ", price_cents: 35000, unit: "video" }],
    })
    expect(body.name).toBe("Launch Duo")
    expect(body.lead_time_days).toBeNull()
    expect(body.included).toEqual(["1 revision"])
    expect(body.addons).toEqual([
      { name: "Extra video", price_cents: 35000, unit: "video" },
    ])
  })
})

describe("sameDraft", () => {
  it("ignores key order and surrounding spaces", () => {
    expect(sameDraft(COMPLETE, { ...COMPLETE, name: " Launch Duo " })).toBe(
      true
    )
    expect(sameDraft(COMPLETE, { ...COMPLETE, volume_count: 3 })).toBe(false)
  })

  it("treats an unset optional field and null as the same", () => {
    expect(sameDraft(COMPLETE, { ...COMPLETE, lead_time_days: null })).toBe(
      true
    )
  })
})

describe("rejectionFrom", () => {
  it("reads an incomplete draft", () => {
    expect(
      rejectionFrom({
        detail: { error: "draft_incomplete", missing: ["name"] },
      })
    ).toEqual({ kind: "incomplete", missing: ["name"] })
  })

  it("reads broken rules", () => {
    const violations = [{ field: "niche", message: "Pick one of your niches." }]
    expect(
      rejectionFrom({ detail: { error: "rules_violated", violations } })
    ).toEqual({ kind: "violations", violations })
  })

  it("is null for anything else", () => {
    expect(rejectionFrom(undefined)).toBeNull()
    expect(rejectionFrom({ detail: "package_not_found" })).toBeNull()
    expect(rejectionFrom({ detail: { error: "other" } })).toBeNull()
    expect(
      rejectionFrom({ detail: { error: "rules_violated", violations: "no" } })
    ).toBeNull()
  })
})

describe("fieldLabel", () => {
  it("names a field the way the card does, and falls back to the key", () => {
    expect(fieldLabel("base_price_cents")).toBe("Base price")
    expect(fieldLabel("something_new")).toBe("something_new")
  })
})

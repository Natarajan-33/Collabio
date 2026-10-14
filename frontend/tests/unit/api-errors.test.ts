import { describe, expect, it } from "vitest"

import { apiErrorCode, apiErrorDetail } from "@/lib/api/errors"

describe("apiErrorCode", () => {
  it("reads the new {detail: {code}} shape", () => {
    expect(
      apiErrorCode({
        detail: {
          code: "terms_changed",
          message: "Changed",
          terms_event_id: 4,
        },
      })
    ).toBe("terms_changed")
  })

  it("reads a string detail", () => {
    expect(apiErrorCode({ detail: "not_found" })).toBe("not_found")
  })

  it("reads the older {error} shape", () => {
    expect(apiErrorCode({ detail: { error: "invalid_brief" } })).toBe(
      "invalid_brief"
    )
  })

  it.each([
    undefined,
    null,
    "boom",
    42,
    {},
    { detail: 3 },
    { detail: {} },
    { detail: [] },
  ])("is null for %j", (value) => {
    expect(apiErrorCode(value)).toBeNull()
  })
})

describe("apiErrorDetail", () => {
  it("returns the detail with its extras", () => {
    const detail = apiErrorDetail<{ below_by_cents: number }>({
      detail: { code: "below_floor", message: "Below", below_by_cents: 100 },
    })
    expect(detail?.code).toBe("below_floor")
    expect(detail?.message).toBe("Below")
    expect(detail?.below_by_cents).toBe(100)
  })

  it("is null for string details, other shapes and non-errors", () => {
    expect(apiErrorDetail({ detail: "not_found" })).toBeNull()
    expect(apiErrorDetail({ detail: { error: "x" } })).toBeNull()
    expect(apiErrorDetail({ detail: { code: "x" } })).toBeNull()
    expect(apiErrorDetail(undefined)).toBeNull()
    expect(apiErrorDetail("x")).toBeNull()
  })
})

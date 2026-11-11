import { describe, expect, it } from "vitest"

import { CALLS_OFF, personaPath, PERSONAS } from "@/lib/hackathon"

describe("hackathon personas", () => {
  it("sends each persona to its deals", () => {
    expect(personaPath("brand")).toBe("/brand/deals")
    expect(personaPath("creator")).toBe("/creator/deals")
  })

  it("names the demo personas", () => {
    expect(PERSONAS.brand.label).toBe("Enter as Lumen Audio (brand)")
    expect(PERSONAS.creator.label).toBe("Enter as Priya (creator)")
  })

  it("explains why calls are off", () => {
    expect(CALLS_OFF).toBe("Calls are off in the public demo.")
  })
})

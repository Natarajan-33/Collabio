import type { components } from "@/lib/api/schema"

/**
 * The niche vocabulary the backend accepts: a brand's category and a creator's niches.
 * Typed from the API schema, so a niche added there fails to compile until labelled here.
 */
export type Niche = components["schemas"]["BrandOnboarding"]["category"]

export const NICHES: readonly { value: Niche; label: string }[] = [
  { value: "consumer_tech", label: "Consumer tech" },
  { value: "beauty", label: "Beauty" },
  { value: "fitness", label: "Fitness" },
  { value: "food", label: "Food" },
  { value: "gaming", label: "Gaming" },
  { value: "b2b_saas", label: "B2B SaaS" },
]

/** Launch regions. The value is the code stored on the creator and used by discovery. */
export const REGIONS = [
  { value: "US", label: "United States" },
  { value: "IN", label: "India" },
  { value: "UK", label: "United Kingdom" },
  { value: "CA", label: "Canada" },
  { value: "AU", label: "Australia" },
] as const

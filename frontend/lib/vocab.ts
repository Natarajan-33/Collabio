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

/** What a package delivers. Typed from the API schema, like `Niche`. */
export type ContentType =
  components["schemas"]["PackageSummary"]["content_type"]

export const CONTENT_TYPES: readonly { value: ContentType; label: string }[] = [
  { value: "short_video", label: "Short video" },
  { value: "long_video", label: "Long video" },
  { value: "story", label: "Story" },
  { value: "live", label: "Live" },
]

/** How a creator likes to be reached first. */
export type PreferredChannel =
  components["schemas"]["PackageSummary"]["preferred_channel"]

export const CHANNELS: readonly { value: PreferredChannel; label: string }[] = [
  { value: "email_first", label: "Email first" },
  { value: "phone_ok", label: "Phone OK" },
  { value: "email_only", label: "Email only" },
]

/**
 * A colour per niche, for the ring round a creator's avatar. Hues keep clear of the
 * ember `--voice` (35) and the gain and loss colours, which mean something else. The
 * lightness is mid-range so a ring reads on both the paper and the dark theme.
 */
export const NICHE_COLOR: Record<Niche, string> = {
  consumer_tech: "oklch(0.62 0.14 250)",
  beauty: "oklch(0.66 0.14 350)",
  fitness: "oklch(0.62 0.12 180)",
  food: "oklch(0.74 0.13 85)",
  gaming: "oklch(0.58 0.15 295)",
  b2b_saas: "oklch(0.55 0.04 255)",
}

export function nicheLabel(value: string): string {
  return NICHES.find((niche) => niche.value === value)?.label ?? value
}

export function contentTypeLabel(value: string): string {
  return CONTENT_TYPES.find((type) => type.value === value)?.label ?? value
}

export function channelLabel(value: string): string {
  return CHANNELS.find((channel) => channel.value === value)?.label ?? value
}

/** The ring colour for a creator: that of the first niche we know a colour for. */
export function nicheColor(niches: readonly string[]): string {
  for (const niche of niches) {
    if (niche in NICHE_COLOR) return NICHE_COLOR[niche as Niche]
  }
  return "var(--muted-foreground)"
}

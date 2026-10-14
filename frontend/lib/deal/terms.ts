import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"

export type TermsDraft = components["schemas"]["TermsDraft"]
export type TermsInput = components["schemas"]["TermsInput"]

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
]

/**
 * A calendar day as `Nov 30, 2026`. Read from the text, not through `Date`, so a day
 * never slips with the viewer's time zone; mirrors the backend's milestone copy.
 */
export function formatDay(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return iso
  const month = MONTHS[Number(match[2]) - 1]
  return month ? `${month} ${Number(match[3])}, ${match[1]}` : iso
}

/**
 * Terms the voice agent heard laid over the ones already on the card. What was spoken
 * wins, but a field the speaker left out keeps its value; spoken conditions are added
 * after the existing ones, and one that is already there (in any case) is not repeated.
 */
export function mergeDraft(
  current: TermsDraft | null,
  spoken: TermsDraft
): TermsDraft {
  const base: TermsDraft = current ?? { conditions: [] }
  const merged: TermsDraft = { ...base, conditions: [...base.conditions] }
  if (spoken.videos != null) merged.videos = spoken.videos
  if (spoken.price_cents != null) merged.price_cents = spoken.price_cents
  if (spoken.go_live_by != null) merged.go_live_by = spoken.go_live_by
  if (spoken.note != null) merged.note = spoken.note

  const seen = new Set(merged.conditions.map((c) => c.trim().toLowerCase()))
  for (const condition of spoken.conditions) {
    const key = condition.trim().toLowerCase()
    if (key === "" || seen.has(key)) continue
    seen.add(key)
    merged.conditions.push(condition)
  }
  return merged
}

/** The terms a request can carry, or null while the draft has no videos or no price. */
export function draftToInput(draft: TermsDraft): TermsInput | null {
  if (draft.videos == null || draft.price_cents == null) return null
  return {
    videos: draft.videos,
    price_cents: draft.price_cents,
    go_live_by: draft.go_live_by ?? null,
    conditions: draft.conditions,
  }
}

const DOLLARS = /^\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?$/

/** `$1,200`, `1200` or `1,200.50` as cents; anything else is null. */
export function parseDollars(text: string): number | null {
  const match = DOLLARS.exec(text.trim())
  if (!match) return null
  const dollars = Number(match[1].replaceAll(",", ""))
  const cents = Number((match[2] ?? "").padEnd(2, "0"))
  return dollars * 100 + cents
}

type SummaryTerms = {
  videos?: number | null
  price_cents?: number | null
  go_live_by?: string | null
}

/** One line for a position: `3 videos · $1,200 · live by Nov 30, 2026`. */
export function termsSummary(terms: SummaryTerms): string {
  const parts: string[] = []
  if (terms.videos != null) {
    parts.push(`${terms.videos} ${terms.videos === 1 ? "video" : "videos"}`)
  }
  if (terms.price_cents != null) parts.push(formatCents(terms.price_cents))
  if (terms.go_live_by) parts.push(`live by ${formatDay(terms.go_live_by)}`)
  return parts.join(" · ")
}

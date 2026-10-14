import type { components } from "@/lib/api/schema"

export type OfferListItem = components["schemas"]["OfferListItem"]
export type OfferCounts = components["schemas"]["OfferCounts"]
export type OfferDesk = components["schemas"]["OfferDesk"]

export type OfferTab = keyof OfferCounts
export type OfferSort = "fit" | "revenue" | "timeline"

export const OFFER_TABS: { key: OfferTab; label: string; empty: string }[] = [
  {
    key: "needs_you",
    label: "Needs you",
    empty: "Nothing needs your reply right now.",
  },
  {
    key: "waiting",
    label: "Waiting",
    empty: "No offers are waiting on a brand.",
  },
  { key: "booked", label: "Booked", empty: "No booked deals yet." },
  { key: "closed", label: "Closed", empty: "No closed offers." },
]

export const OFFER_SORTS: { key: OfferSort; label: string }[] = [
  { key: "fit", label: "Fit" },
  { key: "revenue", label: "Revenue" },
  { key: "timeline", label: "Timeline" },
]

export const DELTA_FLAG_LABEL: Record<OfferListItem["delta_flags"][number], string> = {
  below_base_price: "Below base price",
  lead_time_conflict: "Lead-time conflict",
  estimated: "Estimated",
}

/** The offers on screen as the voice router wants them: who each one is from. */
export function visibleOffers(items: readonly OfferListItem[]) {
  return items.map((item) => ({
    thread_id: item.thread_id,
    brand_name: item.brand.name,
  }))
}

export function offerPath(threadId: string): string {
  return `/creator/offers/${threadId}`
}

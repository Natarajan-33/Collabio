import type { components } from "@/lib/api/schema"
import type { TermsDraft } from "@/lib/deal/terms"

export type OfferListItem = components["schemas"]["OfferListItem"]
export type OfferCounts = components["schemas"]["OfferCounts"]
export type OfferDesk = components["schemas"]["OfferDesk"]

export type OfferTab = keyof OfferCounts
export type OfferSort = "fit" | "revenue" | "timeline"

// Booked offers are not a tab here: they live under Booked (the deals page).
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
  { key: "closed", label: "Closed", empty: "No closed offers." },
]

export const OFFER_SORTS: { key: OfferSort; label: string }[] = [
  { key: "fit", label: "Fit" },
  { key: "revenue", label: "Revenue" },
  { key: "timeline", label: "Timeline" },
]

export const DELTA_FLAG_LABEL: Record<
  OfferListItem["delta_flags"][number],
  string
> = {
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

type TermsColumn = OfferDesk["my_package"]

/** A column as a draft the terms card can edit. */
export function columnToDraft(column: TermsColumn): TermsDraft {
  return {
    videos: column.videos,
    price_cents: column.price_cents,
    go_live_by: column.go_live_by,
    conditions: [...column.conditions],
  }
}

/** The terms a counter starts from: my latest position, else what the brand asked. */
export function counterPrefill(desk: OfferDesk): TermsDraft {
  return columnToDraft(desk.latest ?? desk.their_ask)
}

/**
 * The brand's current offer, the terms accepting would record: its latest counter when
 * it has made one, otherwise the ask in the brief.
 */
export function brandOffer(desk: OfferDesk): TermsColumn {
  return desk.latest && desk.latest_source === "brand"
    ? desk.latest
    : desk.their_ask
}

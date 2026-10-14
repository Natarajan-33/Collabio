import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"
import { contentTypeLabel } from "@/lib/vocab"

type ThreadCard = components["schemas"]["ThreadCard"]
type ThreadStatus = ThreadCard["status"]
type EventType = components["schemas"]["ThreadEventView"]["type"]
type NegotiationTerms = components["schemas"]["NegotiationTerms"]
type ThreadEventView = components["schemas"]["ThreadEventView"]
type BriefSummary = components["schemas"]["BriefSummary"]
type TermsDraft = components["schemas"]["TermsDraft"]

/** The confirming dialogs the brand's drawer can show; the board owns which is open. */
export type BoardDialog =
  | "counter"
  | "resolve"
  | "decline"
  | "withdraw"
  | "award"

export type BoardSortKey = "best_value" | "price" | "status" | "recent"

export const STATUS_LABEL: Record<ThreadStatus, string> = {
  queued: "Queued",
  drafting: "Writing email",
  awaiting_reply: "Sent",
  calling: "Calling…",
  in_call: "In call",
  countered: "Countered",
  accepted: "Accepted",
  declined: "Declined",
  needs_review: "Needs review",
  failed: "Failed",
  awarded: "Booked",
  closed_lost: "Closed",
  no_response: "No reply",
  follow_up_suggested: "No reply · Call?",
}

export const STATUS_TONE: Record<
  ThreadStatus,
  "neutral" | "active" | "positive" | "negative" | "attention"
> = {
  queued: "neutral",
  drafting: "active",
  awaiting_reply: "neutral",
  calling: "active",
  in_call: "active",
  countered: "attention",
  accepted: "positive",
  declined: "negative",
  needs_review: "attention",
  failed: "negative",
  awarded: "positive",
  closed_lost: "neutral",
  no_response: "neutral",
  follow_up_suggested: "attention",
}

const EVENT_LABEL_EXACT: Partial<Record<EventType, string>> = {
  queued: "Queued",
  email_drafted: "Email written",
  email_sent: "Email sent",
  call_placed: "Call placed",
  call_started: "Call connected",
  call_offer_logged: "Offer logged during call",
  call_ended: "Call ended",
  needs_review: "Needs review",
  failed: "Failed",
  retried: "Retried",
  email_received: "Reply received",
  counter_submitted: "Creator countered",
  brand_counter_sent: "You countered",
  accepted: "Accepted",
  declined: "Declined",
  awarded: "Booked",
  closed_lost: "Closed",
  offer_expired: "Offer expired",
}

export function eventLabel(type: EventType): string {
  const exact = EVENT_LABEL_EXACT[type]
  if (exact) return exact
  const words = type.split("_").join(" ")
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export const EVENT_LABEL: Record<EventType, string> = new Proxy(
  {} as Record<EventType, string>,
  {
    get(_target, prop: string) {
      return eventLabel(prop as EventType)
    },
  }
)

const STATUS_ORDER = Object.keys(STATUS_LABEL) as ThreadStatus[]

const LIVE_STATUSES = new Set<ThreadStatus>([
  "queued",
  "drafting",
  "calling",
  "in_call",
])

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

function formatGoLive(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return iso
  const month = MONTHS[Number(match[2]) - 1]
  return month ? `${month} ${Number(match[3])}` : iso
}

function perVideoCents(terms: NegotiationTerms | null): number | null {
  if (!terms?.price_cents || !terms.videos) return null
  return Math.round(terms.price_cents / terms.videos)
}

export function sortThreads(
  threads: ThreadCard[],
  key: BoardSortKey
): ThreadCard[] {
  const sorted = [...threads]
  switch (key) {
    case "best_value":
      sorted.sort((a, b) => {
        const aEl = a.best_value?.eligible ?? false
        const bEl = b.best_value?.eligible ?? false
        if (aEl !== bEl) return aEl ? -1 : 1
        const ar = a.best_value?.rank
        const br = b.best_value?.rank
        if (ar !== null && br !== null && ar !== br) {
          return (ar ?? 999) - (br ?? 999)
        }
        if (ar !== null && br === null) return -1
        if (ar === null && br !== null) return 1
        return a.created_at.localeCompare(b.created_at)
      })
      break
    case "price":
      sorted.sort((a, b) => {
        const ap = perVideoCents(a.latest_terms)
        const bp = perVideoCents(b.latest_terms)
        if (ap === null && bp === null) return 0
        if (ap === null) return 1
        if (bp === null) return -1
        return ap - bp
      })
      break
    case "status":
      sorted.sort(
        (a, b) =>
          STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)
      )
      break
    case "recent":
      sorted.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
      break
  }
  return sorted
}

export function termsLine(terms: NegotiationTerms | null): string {
  if (!terms) return "No terms yet"
  const parts: string[] = []
  if (terms.videos != null) {
    parts.push(
      `${terms.videos} video${terms.videos === 1 ? "" : "s"}`
    )
  }
  if (terms.price_cents != null) {
    parts.push(formatCents(terms.price_cents))
  }
  if (terms.go_live_by) {
    parts.push(`live by ${formatGoLive(terms.go_live_by)}`)
  }
  return parts.length ? parts.join(" · ") : "No terms yet"
}

function relativeAgo(iso: string, now: Date): string {
  const then = new Date(iso).getTime()
  const diffSec = Math.max(0, Math.floor((now.getTime() - then) / 1000))
  if (diffSec < 60) return "just now"
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} min ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr} hr ago`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay} day${diffDay === 1 ? "" : "s"} ago`
}

export function lastEventLine(
  event: ThreadEventView | null,
  now: Date
): string {
  if (!event) return ""
  const label = eventLabel(event.type)
  return `${label} · ${relativeAgo(event.created_at, now)}`
}

export function isLive(threads: ThreadCard[]): boolean {
  return threads.some((t) => LIVE_STATUSES.has(t.status))
}

const VIDEO_NOUNS: Record<string, [string, string]> = {
  short_video: ["short video", "short videos"],
  long_video: ["long video", "long videos"],
  story: ["story", "stories"],
  live: ["live", "lives"],
}

/** The ask line under the board header, e.g. "3 short videos · $1,000 · live by Nov 14". */
export function briefAskLine(brief: BriefSummary): string {
  const nouns =
    VIDEO_NOUNS[brief.deliverables_format] ?? [
      contentTypeLabel(brief.deliverables_format).toLowerCase(),
      contentTypeLabel(brief.deliverables_format).toLowerCase(),
    ]
  const count = brief.deliverables_count
  const videos = `${count} ${nouns[count === 1 ? 0 : 1]}`
  return `${videos} · ${formatCents(brief.ask_price_cents)} · live by ${formatGoLive(brief.go_live_by)}`
}

export function launchedAgo(iso: string, now: Date): string {
  return `Launched ${relativeAgo(iso, now)}`
}

/**
 * Where a counter starts: the creator's latest terms, with anything they left out taken
 * from the brief's ask. The brand edits from here.
 */
export function counterPrefill(
  card: ThreadCard,
  brief: BriefSummary
): TermsDraft {
  const latest = card.latest_terms
  return {
    videos: latest?.videos ?? brief.deliverables_count,
    price_cents: latest?.price_cents ?? brief.ask_price_cents,
    go_live_by: latest?.go_live_by ?? brief.go_live_by,
    conditions: [...(latest?.conditions ?? [])],
  }
}

/** Terms as read from a reply, as an editable draft. What the reply left out stays empty. */
export function termsToDraft(terms: NegotiationTerms | null): TermsDraft {
  return {
    videos: terms?.videos ?? null,
    price_cents: terms?.price_cents ?? null,
    go_live_by: terms?.go_live_by ?? null,
    conditions: [...(terms?.conditions ?? [])],
  }
}

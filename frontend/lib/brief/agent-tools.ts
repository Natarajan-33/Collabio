import type { components } from "@/lib/api/schema"
import {
  MISSING_LABELS,
  formatFieldValue,
  type BriefFieldKey,
} from "@/lib/brief/state"

type DealBrief = components["schemas"]["DealBrief"]
type BriefPatch = components["schemas"]["BriefPatch"]

/** The fields the brief agent's `update_brief` tool may name (`backend/agents/tools/update_brief.json`). */
export const AGENT_FIELDS = [
  "deliverables_count",
  "deliverables_format",
  "deliverable_length_s",
  "go_live_by",
  "ask_price_usd",
  "budget_ceiling_usd",
  "negotiation_ask",
  "flexibility",
  "product_summary",
  "contact_email",
] as const

const FORMATS = ["short_video", "long_video", "story", "live"] as const
const FLEXIBILITY = ["timeline", "price", "deliverables", "none"] as const

// Whole dollars, grouped (1,200) or plain, with an optional $ and up to two decimals.
const DOLLARS = /^\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?$/

/**
 * A dollar amount said in digits, as whole cents. Words, suffixes such as "1.2k",
 * negatives and zero all read as null: nothing the agent got wrong is ever saved.
 */
export function parseDollarsToCents(value: string): number | null {
  const match = DOLLARS.exec(value.trim())
  if (!match) return null
  const dollars = Number(match[1].replaceAll(",", ""))
  const cents = Number((match[2] ?? "").padEnd(2, "0"))
  const total = dollars * 100 + cents
  return Number.isSafeInteger(total) && total > 0 ? total : null
}

const WHOLE_NUMBER = /^\d+$/

function wholeNumber(value: string): number | null {
  const text = value.trim()
  if (!WHOLE_NUMBER.test(text)) return null
  const n = Number(text)
  return Number.isSafeInteger(n) && n > 0 ? n : null
}

/** `YYYY-MM-DD` that is a real calendar day. */
function isIsoDate(text: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  if (!match) return false
  const [year, month, day] = [match[1], match[2], match[3]].map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  )
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

type Parsed = { patch: BriefPatch } | { error: string }

function text(
  field: "negotiation_ask" | "product_summary",
  value: string
): Parsed {
  const trimmed = value.trim()
  return trimmed
    ? { patch: { [field]: trimmed } }
    : { error: "Give some text for that field." }
}

/**
 * What the agent said, as the patch the API takes, or an error the agent can say aloud
 * and re-ask from. The agent speaks dollars; the API takes cents (Ruling 9).
 */
export function agentFieldToPatch(field: string, value: string): Parsed {
  switch (field) {
    case "ask_price_usd":
    case "budget_ceiling_usd": {
      const cents = parseDollarsToCents(value)
      if (cents === null) {
        return { error: "Give the amount in digits, for example 1200." }
      }
      return {
        patch:
          field === "ask_price_usd"
            ? { ask_price_cents: cents }
            : { budget_ceiling_cents: cents },
      }
    }
    case "deliverables_count": {
      const count = wholeNumber(value)
      return count === null
        ? { error: "Give the number of deliverables as a whole number." }
        : { patch: { deliverables_count: count } }
    }
    case "deliverable_length_s": {
      const seconds = wholeNumber(value)
      return seconds === null
        ? { error: "Give the video length as a whole number of seconds." }
        : { patch: { deliverable_length_s: seconds } }
    }
    case "deliverables_format": {
      const format = FORMATS.find((f) => f === value.trim().toLowerCase())
      return format
        ? { patch: { deliverables_format: format } }
        : { error: `Format must be one of ${FORMATS.join(", ")}.` }
    }
    case "go_live_by": {
      const date = value.trim()
      return isIsoDate(date)
        ? { patch: { go_live_by: date } }
        : { error: "Give the date as YYYY-MM-DD." }
    }
    case "flexibility": {
      const items = value
        .split(",")
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean)
      const valid = items.filter((item): item is (typeof FLEXIBILITY)[number] =>
        FLEXIBILITY.some((f) => f === item)
      )
      if (items.length === 0 || valid.length !== items.length) {
        return {
          error: `Flexibility must be ${FLEXIBILITY.slice(0, -1).join(", ")} or ${FLEXIBILITY.at(-1)}.`,
        }
      }
      return { patch: { flexibility: [...new Set(valid)] } }
    }
    case "negotiation_ask":
    case "product_summary":
      return text(field, value)
    case "contact_email": {
      const email = value.trim()
      return EMAIL.test(email)
        ? { patch: { contact_email: email } }
        : { error: "Give a full email address, like name@brand.com." }
    }
    default:
      return {
        error: `I can't set ${field}. Fields: ${AGENT_FIELDS.join(", ")}`,
      }
  }
}

/** The note the agent gets when the brand edits the card mid-conversation. */
export function contextualUpdate(key: BriefFieldKey, brief: DealBrief): string {
  const label = MISSING_LABELS[key] ?? key
  return `The brand set ${label} to ${formatFieldValue(brief, key)} on the card.`
}

/**
 * The creator the agent meant: by full name, first name or handle (with or without `@`),
 * in any case. A full name or handle wins over a first name that two creators share.
 */
export function matchCreator(
  ref: string,
  creators: { creator_id: string; name: string; handle: string }[]
): string | null {
  const wanted = ref.trim().replace(/^@/, "").toLowerCase()
  if (!wanted) return null
  const exact = creators.find(
    (c) =>
      c.name.trim().toLowerCase() === wanted ||
      c.handle.replace(/^@/, "").toLowerCase() === wanted
  )
  if (exact) return exact.creator_id
  const byFirst = creators.find(
    (c) => c.name.trim().split(/\s+/)[0]?.toLowerCase() === wanted
  )
  return byFirst?.creator_id ?? null
}

import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"
import { contentTypeLabel } from "@/lib/vocab"

type DealBrief = components["schemas"]["DealBrief"]

/** The twelve fields a brand edits on the card (the flexibility note is left to the agent). */
export type BriefFieldKey =
  | "brand_name"
  | "product_name"
  | "product_summary"
  | "deliverables_count"
  | "deliverables_format"
  | "deliverable_length_s"
  | "go_live_by"
  | "budget_ceiling_cents"
  | "ask_price_cents"
  | "negotiation_ask"
  | "flexibility"
  | "contact_email"

export type BriefField = {
  key: BriefFieldKey
  label: string
  /** Launch is locked until a required field is filled. */
  required: boolean
  /** Only the brand ever sees it. */
  private?: true
}

/** The card's rows, in order. */
export const BRIEF_FIELDS: readonly BriefField[] = [
  { key: "brand_name", label: "Brand", required: true },
  { key: "product_name", label: "Product", required: true },
  { key: "product_summary", label: "Product summary", required: true },
  { key: "deliverables_count", label: "Deliverables", required: true },
  { key: "deliverables_format", label: "Format", required: true },
  { key: "deliverable_length_s", label: "Video length", required: false },
  { key: "go_live_by", label: "Go live by", required: true },
  {
    key: "budget_ceiling_cents",
    label: "Budget ceiling (private)",
    required: true,
    private: true,
  },
  { key: "ask_price_cents", label: "Opening ask", required: true },
  { key: "negotiation_ask", label: "The ask", required: true },
  { key: "flexibility", label: "Flexible on", required: true },
  { key: "contact_email", label: "Reply-to contact", required: true },
]

/** Mirror of the backend `BRIEF_FIELD_LABELS`: a field as it reads in "Still needed: …". */
export const MISSING_LABELS: Readonly<Record<string, string>> = {
  brand_name: "brand name",
  product_name: "product name",
  product_summary: "product summary",
  deliverables_count: "number of deliverables",
  deliverables_format: "deliverable format",
  deliverable_length_s: "video length",
  go_live_by: "go-live date",
  budget_ceiling_cents: "budget ceiling",
  ask_price_cents: "opening ask",
  negotiation_ask: "what to negotiate for",
  flexibility: "flexibility",
  flexibility_note: "flexibility note",
  contact_email: "contact email",
}

/** The plain-words names of the fields the API reports as missing, in the order given. */
export function missingLabels(keys: readonly string[]): string[] {
  return keys.map((key) => MISSING_LABELS[key] ?? key)
}

export type FieldState = "filled" | "missing" | "changed"

function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === "string") return value.trim() === ""
  return Array.isArray(value) && value.length === 0
}

/** What a row should look like: just saved, still needed, or plain. */
export function fieldState(
  brief: DealBrief,
  key: BriefFieldKey,
  changed: ReadonlySet<BriefFieldKey>
): FieldState {
  if (changed.has(key)) return "changed"
  const field = BRIEF_FIELDS.find((f) => f.key === key)
  return field?.required && isBlank(brief[key]) ? "missing" : "filled"
}

/** The fields whose value differs after a save. The first load has nothing to compare. */
export function changedFields(
  before: DealBrief | null,
  after: DealBrief
): Set<BriefFieldKey> {
  const changed = new Set<BriefFieldKey>()
  if (!before) return changed
  for (const { key } of BRIEF_FIELDS) {
    if (
      JSON.stringify(before[key] ?? null) !== JSON.stringify(after[key] ?? null)
    ) {
      changed.add(key)
    }
  }
  return changed
}

const NOUNS: Record<string, readonly [string, string]> = {
  short_video: ["short video", "short videos"],
  long_video: ["long video", "long videos"],
  story: ["story", "stories"],
  live: ["live stream", "live streams"],
}

const FLEXIBILITY_LABELS: Record<string, string> = {
  timeline: "Timeline",
  price: "Price",
  deliverables: "Deliverables",
  none: "None",
}

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

/** `2026-11-14` as `Nov 14, 2026`, read as text so no time zone can shift the day. */
function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return iso
  const month = MONTHS[Number(match[2]) - 1]
  return month ? `${month} ${Number(match[3])}, ${match[1]}` : iso
}

const EMPTY = "—"

/** A field as the card shows it. An empty field reads as a dash. */
export function formatFieldValue(brief: DealBrief, key: BriefFieldKey): string {
  const value = brief[key]
  if (isBlank(value)) return EMPTY

  switch (key) {
    case "deliverables_count": {
      const count = brief.deliverables_count as number
      const nouns = brief.deliverables_format
        ? NOUNS[brief.deliverables_format]
        : undefined
      return nouns ? `${count} ${nouns[count === 1 ? 0 : 1]}` : String(count)
    }
    case "deliverables_format":
      return contentTypeLabel(value as string)
    case "deliverable_length_s":
      return `${value} s`
    case "go_live_by":
      return formatDate(value as string)
    case "budget_ceiling_cents":
    case "ask_price_cents":
      return formatCents(value as number)
    case "flexibility":
      return (value as string[])
        .map((item) => FLEXIBILITY_LABELS[item] ?? item)
        .join(", ")
    default:
      return String(value)
  }
}

/** The button on the launch bar: how many creators the launch reaches. */
export function launchLabel(count: number): string {
  return `Launch to ${count}`
}

/** Reads the `detail` of a 422 from `PATCH /briefs/{id}`, or null when it is not one. */
export function invalidFieldMessage(
  detail: unknown
): { field: string; message: string } | null {
  if (typeof detail !== "object" || detail === null) return null
  const { error, field, message } = detail as Record<string, unknown>
  if (
    error !== "invalid_field" ||
    typeof field !== "string" ||
    typeof message !== "string"
  ) {
    return null
  }
  return { field, message }
}

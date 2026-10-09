import type { components } from "@/lib/api/schema"
import { nicheLabel } from "@/lib/vocab"

export type PackageDraft = components["schemas"]["PackageDraft"]
export type MyPackage = components["schemas"]["MyPackage"]
export type RuleViolation = components["schemas"]["RuleViolation"]
export type Addon = components["schemas"]["Addon"]
export type Extra = components["schemas"]["Extra"]

/** A draft with nothing in it yet: what a new package starts from. */
export function emptyDraft(): PackageDraft {
  return { included: [], freebies: [], addons: [], extras: [] }
}

/** A draft from outside, with the lists it left out (they are empty, not absent). */
export function completeDraft(draft: Partial<PackageDraft>): PackageDraft {
  return {
    ...draft,
    included: draft.included ?? [],
    freebies: draft.freebies ?? [],
    addons: draft.addons ?? [],
    extras: draft.extras ?? [],
  }
}

/**
 * Mirror of the backend's `REQUIRED_FIELDS`: what a draft needs before it can be saved,
 * in the order the editor asks for it. Lead time and slots per month are optional.
 */
export const REQUIRED_FIELDS = [
  "name",
  "content_type",
  "niche",
  "volume_count",
  "volume_basis",
  "base_price_cents",
  "preferred_channel",
] as const

const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  content_type: "Content type",
  niche: "Niche",
  volume_count: "Videos",
  volume_basis: "Volume basis",
  base_price_cents: "Base price",
  preferred_channel: "Preferred channel",
  lead_time_days: "Lead time",
  slots_per_month: "Slots per month",
  addons: "Add-ons",
  extras: "Extras",
  included: "Included",
  freebies: "Freebies",
  floor_price_cents: "Floor price",
}

/** A field named the way the card names it; an unknown key reads as itself. */
export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field
}

function isBlank(value: unknown): boolean {
  return value == null || (typeof value === "string" && value.trim() === "")
}

/** Required fields the draft has no value for. A blank name counts as missing. */
export function missingFields(draft: PackageDraft): string[] {
  return REQUIRED_FIELDS.filter((field) => isBlank(draft[field]))
}

function itemKey(item: Addon | Extra): string {
  return item.name.trim().toLowerCase()
}

/**
 * Mirror of the backend's `draft_violations`: the publishing rules broken by the values
 * a draft already has. A field it only lacks is `missingFields`' business, not a
 * violation. The server stays the judge; this lets the card say so before asking it.
 */
export function draftViolations(
  draft: PackageDraft,
  niches: readonly string[]
): RuleViolation[] {
  const missing = new Set(missingFields(draft))
  const found: RuleViolation[] = []
  const fail = (field: string, message: string) =>
    found.push({ field, message })

  if (!missing.has("niche") && !niches.includes(draft.niche as string)) {
    const yours = niches.map(nicheLabel).join(", ") || "none set"
    fail("niche", `Pick one of your niches (${yours}).`)
  }
  if (!missing.has("volume_count") && (draft.volume_count as number) < 1) {
    fail("volume_count", "Include at least 1 video.")
  }
  if (
    !missing.has("base_price_cents") &&
    (draft.base_price_cents as number) <= 0
  ) {
    fail("base_price_cents", "Set a base price above $0.")
  }
  for (const [field, noun, items] of [
    ["addons", "add-on", draft.addons],
    ["extras", "extra", draft.extras],
  ] as const) {
    if (items.some((item) => item.name.trim() === "")) {
      fail(field, `Name every ${noun}.`)
    }
    const keys = items.map(itemKey).filter((key) => key !== "")
    if (new Set(keys).size < keys.length) {
      fail(field, `Each ${noun} needs a different name.`)
    }
    if (items.some((item) => item.price_cents <= 0)) {
      fail(field, `Every ${noun} needs a price above $0.`)
    }
  }
  if (draft.slots_per_month != null && draft.slots_per_month < 0) {
    fail("slots_per_month", "Slots per month can't be negative.")
  }
  if (draft.lead_time_days != null && draft.lead_time_days < 0) {
    fail("lead_time_days", "Lead time can't be negative.")
  }
  return found
}

/** The lists joined, with a message or field named twice kept once. */
export function mergeViolations(
  ...lists: readonly (readonly RuleViolation[])[]
): RuleViolation[] {
  const seen = new Set<string>()
  const merged: RuleViolation[] = []
  for (const violation of lists.flat()) {
    const key = `${violation.field}\n${violation.message}`
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(violation)
  }
  return merged
}

/** A saved package as an editable draft: its terms, without id, status, floor or card text. */
export function draftFromPackage(pkg: MyPackage): PackageDraft {
  return {
    name: pkg.name,
    content_type: pkg.content_type,
    niche: pkg.niche,
    volume_count: pkg.volume_count,
    volume_basis: pkg.volume_basis,
    base_price_cents: pkg.base_price_cents,
    currency: pkg.currency,
    included: [...pkg.included],
    freebies: [...pkg.freebies],
    addons: pkg.addons.map((addon) => ({ ...addon })),
    extras: pkg.extras.map((extra) => ({ ...extra })),
    slots_per_month: pkg.slots_per_month,
    lead_time_days: pkg.lead_time_days,
    preferred_channel: pkg.preferred_channel,
  }
}

/**
 * What goes to the server: the draft with its words trimmed. A field the draft does not
 * have stays out of the body (the server leaves it alone), and a field set to null is
 * sent as null (the server clears it).
 */
export function draftBody(draft: PackageDraft): PackageDraft {
  const body: PackageDraft = {
    ...draft,
    included: draft.included.map((item) => item.trim()).filter(Boolean),
    freebies: draft.freebies.map((item) => item.trim()).filter(Boolean),
    addons: draft.addons.map((addon) => ({
      ...addon,
      name: addon.name.trim(),
    })),
    extras: draft.extras.map((extra) => ({
      ...extra,
      name: extra.name.trim(),
    })),
  }
  if (typeof draft.name === "string") body.name = draft.name.trim()
  return body
}

/** True when two drafts would save as the same package. */
export function sameDraft(a: PackageDraft, b: PackageDraft): boolean {
  const canonical = (draft: PackageDraft) => {
    const body = draftBody(draft)
    return JSON.stringify([
      body.name ?? null,
      body.content_type ?? null,
      body.niche ?? null,
      body.volume_count ?? null,
      body.volume_basis ?? null,
      body.base_price_cents ?? null,
      body.included,
      body.freebies,
      body.addons.map((x) => [x.name, x.price_cents, x.unit]),
      body.extras.map((x) => [x.name, x.price_cents]),
      body.slots_per_month ?? null,
      body.lead_time_days ?? null,
      body.preferred_channel ?? null,
    ])
  }
  return canonical(a) === canonical(b)
}

/**
 * Dollars as typed (`900`, `999.5`, `.50`) to whole cents, by digits and not by
 * multiplying, so no amount drifts. Nothing typed, or no digits, is null.
 */
export function parseDollars(text: string): number | null {
  const match = /^(\d*)(?:\.(\d{0,2}))?$/.exec(text.trim())
  if (!match) return null
  const [, whole, fraction = ""] = match
  if (whole === "" && fraction === "") return null
  return Number(whole || "0") * 100 + Number(fraction.padEnd(2, "0"))
}

/** Cents as the text a person would type: `900`, `999.50`. Nothing, or zero, is empty. */
export function dollarsText(cents: number | null | undefined): string {
  if (!cents || cents <= 0) return ""
  const dollars = Math.floor(cents / 100)
  const rest = cents % 100
  return rest === 0
    ? String(dollars)
    : `${dollars}.${String(rest).padStart(2, "0")}`
}

export type Rejection =
  | { kind: "incomplete"; missing: string[] }
  | { kind: "violations"; violations: RuleViolation[] }

function isViolation(value: unknown): value is RuleViolation {
  const v = value as Partial<RuleViolation> | null
  return typeof v?.field === "string" && typeof v?.message === "string"
}

/**
 * Why the package endpoints refused a 422: required fields still missing, or rules
 * broken. Null for any other error body, which the caller reports as a plain failure.
 */
export function rejectionFrom(error: unknown): Rejection | null {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail
  if (typeof detail !== "object" || detail === null) return null

  const { error: kind, missing, violations } = detail as Record<string, unknown>
  if (
    kind === "draft_incomplete" &&
    Array.isArray(missing) &&
    missing.every((field) => typeof field === "string")
  ) {
    return { kind: "incomplete", missing }
  }
  if (
    kind === "rules_violated" &&
    Array.isArray(violations) &&
    violations.every(isViolation)
  ) {
    return { kind: "violations", violations }
  }
  return null
}

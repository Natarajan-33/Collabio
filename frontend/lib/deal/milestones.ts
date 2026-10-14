import type { components } from "@/lib/api/schema"
import { formatDay } from "@/lib/deal/terms"
import { formatCents } from "@/lib/money"

export type AgreedTerms = components["schemas"]["AgreedTerms"]
export type MilestoneDraft = components["schemas"]["MilestoneDraft"]

const MIN_AMOUNT_CENTS = 100
const MAX_TITLE = 80

/**
 * Why `ms` cannot pay out `agreed`; empty when it can. Mirrors the backend's
 * `validate_milestones` word for word and in the same order (count, numbers, amounts,
 * sum, dates, titles) so the editor can show problems as they are typed. The server
 * stays the authority.
 *
 * A wrong count is reported alone: the other checks mean nothing without one
 * milestone per video.
 */
export function milestoneErrors(
  agreed: AgreedTerms,
  ms: readonly MilestoneDraft[]
): string[] {
  const n = agreed.videos
  if (ms.length !== n) return [`Expected ${n} milestones, one per video`]

  const errors: string[] = []
  const seqs = ms.map((m) => m.seq).sort((a, b) => a - b)
  if (seqs.some((seq, i) => seq !== i + 1)) {
    errors.push(`Milestone numbers must run 1 to ${n}`)
  }
  if (ms.some((m) => m.amount_cents < MIN_AMOUNT_CENTS)) {
    errors.push("Each payment must be at least $1")
  }
  const total = ms.reduce((sum, m) => sum + m.amount_cents, 0)
  if (total !== agreed.price_cents) {
    errors.push(
      `Payments add up to ${formatCents(total)}, not the agreed ${formatCents(agreed.price_cents)}`
    )
  }
  // ISO dates compare correctly as text.
  for (const m of [...ms].sort((a, b) => a.seq - b.seq)) {
    if (m.due_date < agreed.go_live_by) {
      errors.push(
        `Video ${m.seq} is due before the agreed go-live date ${formatDay(agreed.go_live_by)}`
      )
    }
  }
  if (
    ms.some((m) => m.title.trim() === "" || [...m.title].length > MAX_TITLE)
  ) {
    errors.push("Every milestone needs a title of at most 80 characters")
  }
  return errors
}

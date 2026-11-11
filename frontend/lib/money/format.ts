import { formatCents } from "@/lib/money"

/** `1M`, `1.24M`, `500K`, `812.4K`, `950`: compact view counts for money UI. */
export function formatViews(views: number): string {
  const trim = (n: number) => String(Number(n.toFixed(2)))
  if (views >= 1_000_000) return `${trim(views / 1_000_000)}M`
  if (views >= 1_000) return `${trim(views / 1_000)}K`
  return String(views)
}

export function formatExample(example: {
  views: number
  bonus_cents: number
}): string {
  const bonus =
    example.bonus_cents > 0
      ? `+${formatCents(example.bonus_cents)}`
      : "no bonus"
  return `${formatViews(example.views)} views → ${bonus}`
}

const LEDGER: Record<string, string> = {
  funded: "Funded via PayPal Checkout",
  payout_queued: "Payout queued",
  payout_sent: "Payout sent via PayPal",
  payout_succeeded: "Payout received",
  payout_failed: "Payout failed",
  payout_rejected: "Payout rejected",
  refunded: "Unspent budget refunded",
}

export function ledgerLabel(kind: string): string {
  return LEDGER[kind] ?? kind
}

type Breakdown = {
  base?: number
  cpm?: number
  tiers?: number
  already_committed?: number
  delta?: number
}

/** The payout engine's breakdown as display lines; zero parts are left out. */
export function breakdownLines(
  b: Breakdown
): { label: string; cents: number }[] {
  const lines: { label: string; cents: number }[] = []
  if (b.base) lines.push({ label: "Agreed price for the video", cents: b.base })
  if (b.cpm) lines.push({ label: "CPM bonus", cents: b.cpm })
  if (b.tiers) lines.push({ label: "Tier bonus", cents: b.tiers })
  if (b.already_committed)
    lines.push({
      label: "Already paid or pending",
      cents: -b.already_committed,
    })
  lines.push({ label: "Owed now", cents: b.delta ?? 0 })
  return lines
}

const PAYOUT_STATUS: Record<string, string> = {
  awaiting_approval: "Waiting for brand approval",
  approved: "Approved · sending",
  sent: "Sent via PayPal · pending",
  success: "Paid",
  failed: "Failed",
  rejected: "Rejected",
}

export function payoutStatusLabel(status: string): string {
  return PAYOUT_STATUS[status] ?? status
}

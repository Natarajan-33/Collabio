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

import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"
import { ledgerLabel } from "@/lib/money/format"

type LedgerEntry = components["schemas"]["LedgerEntry"]

const TIME = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
})

const OUTFLOW = new Set(["payout_sent", "payout_succeeded", "refunded"])

/** Every money movement on the deal, oldest first, with its PayPal reference. */
export function Ledger({ entries }: { entries: LedgerEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No money has moved yet.</p>
    )
  }
  return (
    <ol className="divide-y divide-border rounded-xl border border-border">
      {entries.map((e) => (
        <li
          key={e.id}
          className="flex items-start justify-between gap-4 px-4 py-3 text-sm"
        >
          <div className="min-w-0">
            <p className="font-medium">{ledgerLabel(e.kind)}</p>
            <p className="truncate text-xs text-muted-foreground">
              {TIME.format(new Date(e.created_at))}
              {e.paypal_ref ? ` · PayPal ${e.paypal_ref}` : ""}
            </p>
          </div>
          <span className="shrink-0 num">
            {OUTFLOW.has(e.kind) ? "−" : ""}
            {formatCents(e.amount_cents)}
          </span>
        </li>
      ))}
    </ol>
  )
}

import { Check, Loader2, X } from "lucide-react"

import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"
import {
  breakdownLines,
  formatViews,
  payoutStatusLabel,
} from "@/lib/money/format"
import { cn } from "@/lib/utils"

type Submission = components["schemas"]["SubmissionView"]
type Payout = components["schemas"]["PayoutView"]

function Check2({ ok, label }: { ok: boolean | null; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {ok ? (
        <Check className="size-3.5 text-emerald-500" aria-hidden />
      ) : (
        <X className="size-3.5 text-destructive" aria-hidden />
      )}
      {label}
    </span>
  )
}

/** A payout's PayPal status, with its ids. */
export function PayoutStatus({ payout }: { payout: Payout }) {
  const tone =
    payout.status === "success"
      ? "text-emerald-600 dark:text-emerald-400"
      : payout.status === "failed" || payout.status === "rejected"
        ? "text-destructive"
        : "text-voice-ink"
  const error = payout.last_error as { code?: string; debug_id?: string } | null
  return (
    <div className="text-sm">
      <p className={cn("font-medium", tone)}>
        {formatCents(payout.amount_cents)} · {payoutStatusLabel(payout.status)}
      </p>
      {payout.paypal_batch_id && (
        <p className="text-xs text-muted-foreground">
          PayPal batch {payout.paypal_batch_id}
          {payout.paypal_item_id ? ` · item ${payout.paypal_item_id}` : ""}
        </p>
      )}
      {payout.reject_reason && (
        <p className="text-xs text-muted-foreground">
          Reason: {payout.reject_reason}
        </p>
      )}
      {error?.code && (
        <p className="text-xs text-destructive">
          PayPal said: {error.code}
          {error.debug_id ? ` (debug ${error.debug_id})` : ""}
        </p>
      )}
    </div>
  )
}

/** Claude's verdict on one submission, and the payout it led to. */
export function VerdictCard({
  submission,
  payout,
}: {
  submission: Submission
  payout?: Payout
}) {
  if (submission.status === "submitted") {
    const failed = submission.run_status === "error"
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        {failed ? (
          <span className="text-destructive">
            Claude couldn&apos;t finish checking this post.
          </span>
        ) : (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Claude is checking the post and reading the views…
          </>
        )}
      </div>
    )
  }

  const breakdown = (payout?.breakdown ?? {}) as Record<string, number>
  return (
    <div className="space-y-2 rounded-lg bg-muted/40 p-3 text-sm">
      {submission.status === "needs_changes" ? (
        <p className="text-voice-ink">{submission.agent_summary}</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <Check2 ok={submission.brief_ok} label="Brief" />
            <Check2 ok={submission.disclosure_ok} label="Disclosure" />
            <span className="num">
              {formatViews(submission.views ?? 0)} views read
              <span className="text-muted-foreground">
                {" "}
                (claimed {formatViews(submission.claimed_views)},{" "}
                {submission.view_confidence} confidence)
              </span>
            </span>
          </div>
          {submission.missing_points.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Missing: {submission.missing_points.join("; ")}
            </p>
          )}
          {submission.agent_summary && (
            <p className="text-xs text-muted-foreground">
              Claude: {submission.agent_summary}
            </p>
          )}
        </>
      )}
      {payout && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            Why this amount?
          </summary>
          <ul className="mt-1 space-y-0.5">
            {breakdownLines(breakdown).map((line) => (
              <li key={line.label} className="flex justify-between gap-3">
                <span>{line.label}</span>
                <span className="num">{formatCents(line.cents)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-muted-foreground">
            Amounts come from the deal terms, never from the AI.
          </p>
        </details>
      )}
      {payout && <PayoutStatus payout={payout} />}
    </div>
  )
}

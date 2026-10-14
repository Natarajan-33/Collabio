"use client"

import { Input } from "@/components/ui/input"
import { MoneyInput } from "@/components/ui/money-input"
import { milestoneErrors } from "@/lib/deal/milestones"
import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"
import { cn } from "@/lib/utils"

type AgreedTerms = components["schemas"]["AgreedTerms"]
type MilestoneDraft = components["schemas"]["MilestoneDraft"]

export type MilestoneEditorProps = {
  agreed: AgreedTerms
  value: MilestoneDraft[]
  onChange: (next: MilestoneDraft[]) => void
  disabled?: boolean
}

/**
 * The payment schedule of a deal about to be booked: one row per video (rows can be
 * edited, never added or removed), a running total against the agreed price, and the
 * same checks the server makes, written out as they are typed. The server stays the
 * authority; these only save a round trip.
 */
export function MilestoneEditor({
  agreed,
  value,
  onChange,
  disabled = false,
}: MilestoneEditorProps) {
  const errors = milestoneErrors(agreed, value)
  const total = value.reduce((sum, m) => sum + m.amount_cents, 0)
  const matches = total === agreed.price_cents

  const edit = (index: number, patch: Partial<MilestoneDraft>) =>
    onChange(value.map((m, i) => (i === index ? { ...m, ...patch } : m)))

  return (
    <fieldset
      disabled={disabled}
      data-slot="milestone-editor"
      className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0"
    >
      <ol className="flex flex-col gap-3">
        {value.map((m, index) => (
          <li
            key={m.seq}
            className="grid items-center gap-2 sm:grid-cols-[2rem_minmax(0,1fr)_8rem_10rem]"
          >
            <span className="num text-sm text-muted-foreground">{m.seq}</span>
            <Input
              aria-label={`Video ${m.seq} title`}
              value={m.title}
              maxLength={80}
              autoComplete="off"
              onChange={(event) => edit(index, { title: event.target.value })}
              className="h-9"
            />
            <MoneyInput
              aria-label={`Video ${m.seq} payment`}
              value={m.amount_cents || null}
              onValueChange={(next) => edit(index, { amount_cents: next ?? 0 })}
              className="h-9"
            />
            <Input
              aria-label={`Video ${m.seq} due date`}
              type="date"
              value={m.due_date}
              onChange={(event) =>
                edit(index, { due_date: event.target.value })
              }
              className="h-9 num"
            />
          </li>
        ))}
      </ol>

      <p
        data-testid="milestone-total"
        className={cn(
          "text-sm",
          matches ? "text-muted-foreground" : "font-medium text-destructive"
        )}
      >
        Total <span className="num">{formatCents(total)}</span> of{" "}
        <span className="num">{formatCents(agreed.price_cents)}</span>
      </p>

      {errors.length > 0 ? (
        <ul
          role="alert"
          className="flex flex-col gap-0.5 text-sm text-destructive"
        >
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}
    </fieldset>
  )
}

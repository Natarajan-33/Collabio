"use client"

import { Plus, X } from "lucide-react"
import * as React from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { MoneyInput } from "@/components/ui/money-input"
import { Stepper } from "@/components/ui/stepper"
import type { TermsDraft } from "@/lib/deal/terms"
import { formatCents } from "@/lib/money"
import { cn } from "@/lib/utils"

const MAX_VIDEOS = 50
const MAX_NOTE = 1000

export type TermsCardProps = {
  value: TermsDraft
  onChange: (next: TermsDraft) => void
  /** How far the price is below the creator's private floor, in cents; null for none. */
  floorWarningCents?: number | null
  /** A sentence about the brand's private ceiling, shown as given; null for none. */
  ceilingMessage?: string | null
  /** Offer a note to the other side (up to 1000 characters). */
  showNote?: boolean
  disabled?: boolean
}

type FieldProps = {
  name: string
  label: string
  /** The control is a text control, which the label points at. */
  inputId?: string
  labelId?: string
  /** Required and still empty: outlined, and says so in words. */
  missing?: boolean
  children: React.ReactNode
}

function Field({
  name,
  label,
  inputId,
  labelId,
  missing = false,
  children,
}: FieldProps) {
  return (
    <div
      data-field={name}
      data-missing={missing ? "" : undefined}
      className={cn(
        "flex min-w-0 flex-col gap-2 rounded-lg",
        missing && "voice-missing"
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <Label id={labelId} htmlFor={inputId}>
          {label}
        </Label>
        {missing ? (
          <span className="text-xs font-medium text-voice-ink">Needed</span>
        ) : null}
      </div>
      {children}
    </div>
  )
}

/**
 * The terms being offered, countered or accepted: videos, price, go-live date, other
 * conditions and an optional note. A controlled card; it says what changed through
 * `onChange` and the page decides what to do with it. Videos or a price the draft does
 * not have yet (a voice draft starts that way) are outlined and marked "Needed".
 */
export function TermsCard({
  value,
  onChange,
  floorWarningCents = null,
  ceilingMessage = null,
  showNote = false,
  disabled = false,
}: TermsCardProps) {
  const videosLabelId = React.useId()
  const priceId = React.useId()
  const dateId = React.useId()
  const conditionId = React.useId()
  const noteId = React.useId()
  const [condition, setCondition] = React.useState("")

  const set = (patch: Partial<TermsDraft>) => onChange({ ...value, ...patch })

  function addCondition() {
    const text = condition.trim()
    if (text === "") return
    setCondition("")
    const exists = value.conditions.some(
      (c) => c.trim().toLowerCase() === text.toLowerCase()
    )
    if (!exists) set({ conditions: [...value.conditions, text] })
  }

  const note = value.note ?? ""
  const warnings = [
    floorWarningCents != null && floorWarningCents > 0 ? (
      <p key="floor">
        That&apos;s{" "}
        <span className="num">{formatCents(floorWarningCents)}</span> below your
        floor
      </p>
    ) : null,
    ceilingMessage ? <p key="ceiling">{ceilingMessage}</p> : null,
  ].filter(Boolean)

  return (
    <fieldset
      disabled={disabled}
      data-slot="terms-card"
      className="m-0 flex min-w-0 flex-col gap-5 rounded-2xl border bg-card p-5 text-card-foreground"
    >
      <div className="grid gap-5 sm:grid-cols-2">
        <Field
          name="videos"
          label="Videos"
          labelId={videosLabelId}
          missing={value.videos == null}
        >
          <Stepper
            labelledBy={videosLabelId}
            noun="videos"
            min={1}
            max={MAX_VIDEOS}
            value={value.videos ?? null}
            onValueChange={(next) => set({ videos: next })}
            className="self-start"
          />
        </Field>
        <Field
          name="price_cents"
          label="Price"
          inputId={priceId}
          missing={value.price_cents == null}
        >
          <MoneyInput
            id={priceId}
            value={value.price_cents ?? null}
            onValueChange={(next) => set({ price_cents: next })}
            className="h-10"
          />
        </Field>
      </div>

      <Field name="go_live_by" label="Go live by" inputId={dateId}>
        <Input
          id={dateId}
          type="date"
          value={value.go_live_by ?? ""}
          onChange={(event) => set({ go_live_by: event.target.value || null })}
          className="h-10 num sm:w-48"
        />
      </Field>

      {warnings.length > 0 ? (
        <div
          role="status"
          data-slot="terms-warnings"
          className="flex flex-col gap-1 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {warnings}
        </div>
      ) : null}

      <Field name="conditions" label="Conditions" inputId={conditionId}>
        {value.conditions.length > 0 ? (
          <ul className="flex flex-wrap gap-2">
            {value.conditions.map((text, index) => (
              <li
                key={`${text}-${index}`}
                className="inline-flex h-8 items-center gap-1 rounded-full border bg-muted/50 pr-1 pl-3 text-sm"
              >
                <span>{text}</span>
                <button
                  type="button"
                  aria-label={`Remove condition ${text}`}
                  onClick={() =>
                    set({
                      conditions: value.conditions.filter(
                        (_, i) => i !== index
                      ),
                    })
                  }
                  className="flex size-6 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50"
                >
                  <X aria-hidden className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex gap-2">
          <Input
            id={conditionId}
            aria-label="Add a condition"
            placeholder="e.g. No exclusivity"
            value={condition}
            maxLength={200}
            autoComplete="off"
            onChange={(event) => setCondition(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault()
                addCondition()
              }
            }}
            className="h-9"
          />
          <Button
            type="button"
            variant="outline"
            className="h-9"
            disabled={condition.trim() === ""}
            onClick={addCondition}
          >
            <Plus aria-hidden />
            Add
          </Button>
        </div>
      </Field>

      {showNote ? (
        <Field name="note" label="Note" inputId={noteId}>
          <textarea
            id={noteId}
            value={note}
            maxLength={MAX_NOTE}
            rows={3}
            onChange={(event) => set({ note: event.target.value || null })}
            className="w-full min-w-0 resize-y rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30"
          />
          <p className="text-right num text-xs text-muted-foreground">
            {note.length} / {MAX_NOTE}
          </p>
        </Field>
      ) : null}
    </fieldset>
  )
}

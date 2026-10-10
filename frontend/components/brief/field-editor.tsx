"use client"

import { LoaderCircle } from "lucide-react"
import * as React from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { MoneyInput } from "@/components/ui/money-input"
import { NativeSelect } from "@/components/ui/native-select"
import { Stepper } from "@/components/ui/stepper"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { components } from "@/lib/api/schema"
import type { BriefField, BriefFieldKey } from "@/lib/brief/state"
import { CONTENT_TYPES } from "@/lib/vocab"

type DealBrief = components["schemas"]["DealBrief"]
type BriefPatch = components["schemas"]["BriefPatch"]

type Kind =
  | "text"
  | "email"
  | "money"
  | "count"
  | "seconds"
  | "format"
  | "date"
  | "flexibility"

const KINDS: Record<BriefFieldKey, Kind> = {
  brand_name: "text",
  product_name: "text",
  product_summary: "text",
  deliverables_count: "count",
  deliverables_format: "format",
  deliverable_length_s: "seconds",
  go_live_by: "date",
  budget_ceiling_cents: "money",
  ask_price_cents: "money",
  negotiation_ask: "text",
  flexibility: "flexibility",
  contact_email: "email",
}

const FLEXIBILITY: readonly { value: string; label: string }[] = [
  { value: "timeline", label: "Timeline" },
  { value: "price", label: "Price" },
  { value: "deliverables", label: "Deliverables" },
  { value: "none", label: "None" },
]

/** The longest product summary the API takes. */
const SUMMARY_MAX = 200

/** What is being typed: text for the text-like kinds, a number for money and count. */
type Draft = string | number | null | string[]

function initialDraft(brief: DealBrief, key: BriefFieldKey, kind: Kind): Draft {
  const value = brief[key]
  switch (kind) {
    case "money":
      return (value as number | null | undefined) ?? null
    case "count":
      // A stepper has no empty state: start from one deliverable.
      return (value as number | null | undefined) ?? 1
    case "seconds":
      return value == null ? "" : String(value)
    case "flexibility":
      return [...brief.flexibility]
    default:
      return (value as string | null | undefined) ?? ""
  }
}

/** The patch for one field. Emptying a field clears it. */
function patchFor(key: BriefFieldKey, kind: Kind, draft: Draft): BriefPatch {
  let value: string | number | string[] | null
  switch (kind) {
    case "money":
    case "count":
      value = draft as number | null
      break
    case "seconds": {
      const number = Number.parseInt(draft as string, 10)
      value = Number.isNaN(number) ? null : number
      break
    }
    case "flexibility":
      value = (draft as string[]).length > 0 ? (draft as string[]) : null
      break
    default: {
      const text = (draft as string).trim()
      value = text === "" ? null : text
    }
  }
  return { [key]: value } as BriefPatch
}

/** None stands alone: choosing it clears the rest, and choosing anything else clears it. */
function nextFlexibility(before: string[], after: string[]): string[] {
  const added = after.filter((item) => !before.includes(item))
  if (added.includes("none")) return ["none"]
  return after.filter((item) => item !== "none")
}

type FieldEditorProps = {
  field: BriefField
  brief: DealBrief
  /** Id of the element that holds the field's visible label. */
  labelId: string
  /** Why the last save failed, shown under the field. */
  error: string | null
  saving: boolean
  onSave: (patch: BriefPatch) => void
  onCancel: () => void
}

/** Edits one brief field in place. Enter or Save commits; Escape or Cancel leaves it as it was. */
export function FieldEditor({
  field,
  brief,
  labelId,
  error,
  saving,
  onSave,
  onCancel,
}: FieldEditorProps) {
  const kind = KINDS[field.key]
  const errorId = React.useId()
  const [draft, setDraft] = React.useState<Draft>(() =>
    initialDraft(brief, field.key, kind)
  )

  const text = typeof draft === "string" ? draft : ""
  const describedBy = error ? errorId : undefined

  function control() {
    switch (kind) {
      case "money":
        return (
          <MoneyInput
            autoFocus
            aria-labelledby={labelId}
            aria-describedby={describedBy}
            aria-invalid={error ? true : undefined}
            value={draft as number | null}
            onValueChange={setDraft}
          />
        )
      case "count":
        return (
          <Stepper
            labelledBy={labelId}
            describedBy={describedBy}
            noun="deliverables"
            min={1}
            value={draft as number}
            onValueChange={(next) => setDraft(next ?? 1)}
            invalid={Boolean(error)}
          />
        )
      case "format":
        return (
          <NativeSelect
            autoFocus
            aria-labelledby={labelId}
            aria-describedby={describedBy}
            aria-invalid={error ? true : undefined}
            value={text}
            onChange={(event) => setDraft(event.target.value)}
          >
            <option value="">Choose a format</option>
            {CONTENT_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </NativeSelect>
        )
      case "flexibility":
        return (
          <ToggleGroup
            multiple
            aria-labelledby={labelId}
            aria-describedby={describedBy}
            variant="outline"
            className="flex-wrap"
            value={draft as string[]}
            onValueChange={(next) =>
              setDraft((before) =>
                nextFlexibility(before as string[], next as string[])
              )
            }
          >
            {FLEXIBILITY.map((option) => (
              <ToggleGroupItem
                key={option.value}
                value={option.value}
                className="aria-pressed:border-foreground aria-pressed:bg-foreground aria-pressed:text-background aria-pressed:hover:bg-foreground/90 aria-pressed:hover:text-background"
              >
                {option.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )
      case "seconds":
        return (
          <Input
            autoFocus
            type="number"
            min={1}
            inputMode="numeric"
            aria-labelledby={labelId}
            aria-describedby={describedBy}
            aria-invalid={error ? true : undefined}
            value={text}
            onChange={(event) => setDraft(event.target.value)}
            className="num"
          />
        )
      default:
        return (
          <Input
            autoFocus
            type={
              kind === "date" ? "date" : kind === "email" ? "email" : "text"
            }
            maxLength={
              field.key === "product_summary" ? SUMMARY_MAX : undefined
            }
            aria-labelledby={labelId}
            aria-describedby={describedBy}
            aria-invalid={error ? true : undefined}
            value={text}
            onChange={(event) => setDraft(event.target.value)}
            className={kind === "date" ? "num" : undefined}
          />
        )
    }
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        if (!saving) onSave(patchFor(field.key, kind, draft))
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel()
      }}
    >
      {control()}
      {error ? (
        <p id={errorId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={saving}>
          {saving ? (
            <LoaderCircle aria-hidden className="animate-spin" />
          ) : null}
          Save
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

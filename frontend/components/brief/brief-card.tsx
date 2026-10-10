"use client"

import { Check, Lock, Pencil } from "lucide-react"
import * as React from "react"

import { FieldEditor } from "@/components/brief/field-editor"
import { Button } from "@/components/ui/button"
import type { components } from "@/lib/api/schema"
import {
  BRIEF_FIELDS,
  fieldState,
  formatFieldValue,
  type BriefFieldKey,
} from "@/lib/brief/state"
import { cn } from "@/lib/utils"

type DealBrief = components["schemas"]["DealBrief"]
type BriefPatch = components["schemas"]["BriefPatch"]

/** How long a just-saved field stays marked. */
const FLASH_MS = 1200

/** Fields that read as figures: prices, counts, dates and durations. */
const NUMERIC = new Set<BriefFieldKey>([
  "deliverables_count",
  "deliverable_length_s",
  "go_live_by",
  "budget_ceiling_cents",
  "ask_price_cents",
])

const NO_FLASH: ReadonlySet<BriefFieldKey> = new Set()

type BriefCardProps = {
  brief: DealBrief
  /** Fields the latest save changed; each is marked for a moment. Pass a new set per save. */
  changed: ReadonlySet<BriefFieldKey>
  /** Saves one field. Resolves to why it was refused, or null once it is saved. */
  onEdit: (key: BriefFieldKey, patch: BriefPatch) => Promise<string | null>
}

/**
 * The brief as it stands: one row per field, a ember outline on what launch still
 * needs, a short wash on what was just saved, and a pencil that opens the field's editor
 * in place. The budget ceiling is marked private: only the brand ever sees it.
 */
export function BriefCard({ brief, changed, onEdit }: BriefCardProps) {
  const idPrefix = React.useId()
  const [editing, setEditing] = React.useState<BriefFieldKey | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [failure, setFailure] = React.useState<{
    key: BriefFieldKey
    message: string
  } | null>(null)

  // A new `changed` set restarts the flash, and a timer ends it. The state still flips
  // when the user prefers reduced motion; only the wash (CSS) is suppressed.
  const [flash, setFlash] = React.useState({ source: changed, keys: changed })
  if (flash.source !== changed) setFlash({ source: changed, keys: changed })
  React.useEffect(() => {
    if (flash.keys.size === 0) return
    const timer = setTimeout(
      () => setFlash((current) => ({ ...current, keys: NO_FLASH })),
      FLASH_MS
    )
    return () => clearTimeout(timer)
  }, [flash])

  async function save(key: BriefFieldKey, patch: BriefPatch) {
    setSaving(true)
    setFailure(null)
    let message: string | null
    try {
      message = await onEdit(key, patch)
    } catch {
      message = "Couldn't save. Try again."
    }
    setSaving(false)
    if (message === null) setEditing(null)
    else setFailure({ key, message })
  }

  return (
    <section
      aria-label="Brief"
      className="rounded-2xl border bg-card p-4 sm:p-6"
    >
      <ul className="flex flex-col gap-3 px-2">
        {BRIEF_FIELDS.map((field) => {
          const state = fieldState(brief, field.key, flash.keys)
          const labelId = `${idPrefix}-${field.key}`
          const open = editing === field.key
          const broken = brief.violations.filter((v) => v.field === field.key)

          return (
            <li
              key={field.key}
              data-field={field.key}
              data-state={state}
              className={cn(
                "flex flex-col gap-1 rounded-lg px-2 py-2 transition-colors",
                state === "missing" && "voice-missing",
                state === "changed" && "field-flash"
              )}
            >
              <div className="flex items-center gap-1.5 text-xs tracking-wide text-muted-foreground uppercase">
                <span id={labelId}>{field.label}</span>
                {field.private ? (
                  <>
                    <Lock aria-hidden className="size-3" />
                    <span className="sr-only">Only you can see this</span>
                  </>
                ) : null}
                {state === "missing" ? (
                  <span className="sr-only">Still needed</span>
                ) : null}
                {state === "changed" ? (
                  <span className="ml-auto inline-flex items-center gap-1 text-voice-ink normal-case">
                    <Check aria-hidden className="size-3" />
                    Updated
                  </span>
                ) : null}
              </div>

              {open ? (
                <FieldEditor
                  field={field}
                  brief={brief}
                  labelId={labelId}
                  error={failure?.key === field.key ? failure.message : null}
                  saving={saving}
                  onSave={(patch) => void save(field.key, patch)}
                  onCancel={() => {
                    setEditing(null)
                    setFailure(null)
                  }}
                />
              ) : (
                <div className="flex items-start justify-between gap-3">
                  <p
                    className={cn(
                      "min-w-0 text-sm break-words",
                      NUMERIC.has(field.key) &&
                        brief[field.key] != null &&
                        "num"
                    )}
                  >
                    {formatFieldValue(brief, field.key)}
                  </p>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Edit ${field.label}`}
                    onClick={() => {
                      setFailure(null)
                      setEditing(field.key)
                    }}
                  >
                    <Pencil aria-hidden />
                  </Button>
                </div>
              )}

              {broken.map((violation) => (
                <p key={violation.message} className="text-sm text-destructive">
                  {violation.message}
                </p>
              ))}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

"use client"

import { Lock, LoaderCircle, Plus, X } from "lucide-react"
import * as React from "react"

import { ChipGroup } from "@/components/auth/chip-group"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import CountUp from "@/components/ui/count-up"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { MoneyInput } from "@/components/ui/money-input"
import { NativeSelect } from "@/components/ui/native-select"
import { Stepper } from "@/components/ui/stepper"
import { formatCents } from "@/lib/money"
import {
  fieldLabel,
  type Addon,
  type PackageDraft,
  type RuleViolation,
} from "@/lib/packages/draft"
import { cn } from "@/lib/utils"
import {
  CHANNELS,
  CONTENT_TYPES,
  NICHES,
  VOLUME_BASES,
  type ContentType,
  type Niche,
  type PreferredChannel,
  type VolumeBasis,
} from "@/lib/vocab"

/** Where a package stands: `null` for a draft the server has not seen. */
export type PackageStatus = "draft" | "published" | null

export type PackageDraftCardProps = {
  draft: PackageDraft
  /** Required fields with no value yet: each gets a pulsing outline. */
  missing: readonly string[]
  /** Rules the draft breaks, shown under the field each one names. */
  violations: readonly RuleViolation[]
  onChange: (draft: PackageDraft) => void
  onSave: () => void
  onPublish: () => void
  /** The creator's own niches: a package can use no others. */
  niches: readonly string[]
  status?: PackageStatus
  /** There are changes the server does not have. Defaults to true. */
  dirty?: boolean
  /** What is being sent to the server; the card is locked meanwhile. */
  pending?: "save" | "publish" | "floor" | null
  /** The private floor as saved, or null for none. */
  floorCents?: number | null
  /** Sets the floor. Without it, or before the package is saved, the floor is read-only. */
  onFloorSave?: (cents: number) => void
  /** Closes the card without saving. */
  onDiscard?: () => void
}

// The price ---------------------------------------------------------------------------

const isWhole = (cents: number | null): cents is number =>
  cents !== null && cents % 100 === 0

/**
 * The base price in large figures. When it changes it counts from the old figure to the
 * new, but a price first shown just appears, and a price with cents is not counted
 * through (it would pass through amounts nobody set).
 */
function AnimatedPrice({ cents }: { cents: number | null }) {
  const [seen, setSeen] = React.useState<{
    cents: number | null
    from: number | null
  }>({ cents, from: null })
  if (seen.cents !== cents) setSeen({ cents, from: seen.cents })

  const from = seen.from
  const counting =
    from !== null && isWhole(from) && isWhole(cents) && from !== cents

  return (
    <p data-slot="price" className="num text-3xl leading-none font-medium">
      <span className="sr-only">
        Base price {cents === null ? "not set" : formatCents(cents)}
      </span>
      <span aria-hidden>
        {cents === null ? (
          <span className="text-muted-foreground">—</span>
        ) : counting ? (
          <>
            $
            <CountUp
              key={`${from}-${cents}`}
              from={from / 100}
              to={cents / 100}
              duration={0.8}
              separator=","
            />
          </>
        ) : (
          formatCents(cents)
        )}
      </span>
    </p>
  )
}

// Fields ------------------------------------------------------------------------------

type FieldControl = {
  /** Id of the field's label: for a group, `aria-labelledby`. */
  labelId: string
  /** Id for a text control, which its label points at. */
  inputId: string
  /** Id of the field's messages, once it has any. */
  describedBy: string | undefined
  invalid: boolean
}

type FieldProps = {
  /** The draft field this is, which is what `missing` and violations name. */
  name: string
  label?: string
  /** A text control: the label is a real `<label>` for it. */
  text?: boolean
  optional?: boolean
  missing: readonly string[]
  violations: readonly RuleViolation[]
  children: (control: FieldControl) => React.ReactNode
}

/**
 * One field of the package: its label, its control and what is wrong with it. A field
 * the draft still needs is outlined in the voice colour and says "Needed" in words too.
 */
function Field({
  name,
  label = fieldLabel(name),
  text = false,
  optional = false,
  missing,
  violations,
  children,
}: FieldProps) {
  const labelId = React.useId()
  const inputId = React.useId()
  const messagesId = React.useId()
  const isMissing = missing.includes(name)
  const messages = violations.filter((v) => v.field === name)
  const invalid = messages.length > 0

  return (
    <div
      data-field={name}
      data-missing={isMissing ? "" : undefined}
      className={cn(
        "flex min-w-0 flex-col gap-2 rounded-lg",
        isMissing && "voice-missing"
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <Label id={labelId} htmlFor={text ? inputId : undefined}>
          {label}
        </Label>
        {isMissing ? (
          <span className="text-xs font-medium text-voice-ink">Needed</span>
        ) : optional ? (
          <span className="text-xs text-muted-foreground">Optional</span>
        ) : null}
      </div>
      {children({
        labelId,
        inputId,
        describedBy: invalid ? messagesId : undefined,
        invalid,
      })}
      {invalid ? (
        <div id={messagesId} className="flex flex-col gap-0.5">
          {messages.map((violation) => (
            <p key={violation.message} className="text-sm text-destructive">
              {violation.message}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** A line of other terms (what is included, freebies, extras) that can be taken off. */
function TermList({
  name,
  noun,
  terms,
  onRemove,
  missing,
  violations,
}: {
  name: "included" | "freebies" | "extras"
  noun: string
  terms: readonly string[]
  onRemove: (index: number) => void
  missing: readonly string[]
  violations: readonly RuleViolation[]
}) {
  return (
    <Field name={name} missing={missing} violations={violations}>
      {({ describedBy }) => (
        <ul aria-describedby={describedBy} className="flex flex-wrap gap-2">
          {terms.map((term, index) => (
            <li
              key={`${term}-${index}`}
              className="inline-flex h-8 items-center gap-1 rounded-full border bg-muted/50 pr-1 pl-3 text-sm"
            >
              <span className="num">{term}</span>
              <button
                type="button"
                aria-label={`Remove ${noun} ${term.split(" · ")[0]}`}
                onClick={() => onRemove(index)}
                className="flex size-6 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Field>
  )
}

// The private floor -------------------------------------------------------------------

function FloorPanel({
  baseCents,
  floorCents,
  enabled,
  pending,
  violations,
  onSave,
}: {
  baseCents: number | null | undefined
  floorCents: number | null
  /** The package is saved, so the server can hold a floor for it. */
  enabled: boolean
  pending: boolean
  violations: readonly RuleViolation[]
  onSave: (cents: number) => void
}) {
  const titleId = React.useId()
  const inputId = React.useId()
  const messageId = React.useId()

  // What has been typed since the floor last changed; undefined while nothing has.
  const [typed, setTyped] = React.useState<number | null | undefined>(undefined)
  const [seenFloor, setSeenFloor] = React.useState(floorCents)
  if (seenFloor !== floorCents) {
    setSeenFloor(floorCents)
    setTyped(undefined)
  }
  const value = typed === undefined ? floorCents : typed

  const messages = violations
    .filter((v) => v.field === "floor_price_cents")
    .map((v) => v.message)
  if (value != null && baseCents != null && value > baseCents) {
    messages.unshift(
      `Your floor can't be above the base price (${formatCents(baseCents)}).`
    )
  }
  const unique = [...new Set(messages)]
  const invalid = unique.length > 0
  const canSet =
    enabled &&
    !pending &&
    !invalid &&
    value != null &&
    value > 0 &&
    value !== floorCents

  return (
    <section
      aria-labelledby={titleId}
      className="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/40 p-4"
    >
      <p id={titleId} className="flex items-center gap-2 text-sm font-medium">
        <Lock aria-hidden className="size-4" />
        Private — only you see this
      </p>
      <p className="text-xs text-muted-foreground">
        The lowest price you would accept. Brands never see it, and it can never
        be above your base price.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex min-w-40 flex-1 flex-col gap-2">
          <Label htmlFor={inputId}>Floor price</Label>
          <MoneyInput
            id={inputId}
            value={value ?? null}
            onValueChange={setTyped}
            disabled={!enabled}
            aria-invalid={invalid ? true : undefined}
            aria-describedby={invalid ? messageId : undefined}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8"
          disabled={!canSet}
          onClick={() => value != null && onSave(value)}
        >
          Set floor
        </Button>
      </div>
      {invalid ? (
        <div id={messageId} className="flex flex-col gap-0.5">
          {unique.map((message) => (
            <p key={message} className="text-sm text-destructive">
              {message}
            </p>
          ))}
        </div>
      ) : null}
      {!enabled ? (
        <p className="text-xs text-muted-foreground">
          Save the package first, then set your floor.
        </p>
      ) : null}
    </section>
  )
}

// The card ----------------------------------------------------------------------------

const KNOWN_FIELDS = new Set([
  "name",
  "content_type",
  "niche",
  "volume_count",
  "volume_basis",
  "base_price_cents",
  "preferred_channel",
  "lead_time_days",
  "slots_per_month",
  "addons",
  "extras",
  "included",
  "freebies",
  "floor_price_cents",
])

const STATUS_LABEL = { new: "New", draft: "Draft", published: "Published" }

/**
 * The package being built, by voice or by hand. Each field is edited in place with
 * chips, steppers and money inputs; a field the draft still needs is outlined, and a
 * rule the draft breaks is written under the field to change. Nothing here saves: the
 * card says what the creator chose (`onSave`, `onPublish`) and the page does it.
 */
export function PackageDraftCard({
  draft,
  missing,
  violations,
  onChange,
  onSave,
  onPublish,
  niches,
  status = null,
  dirty = true,
  pending = null,
  floorCents = null,
  onFloorSave,
  onDiscard,
}: PackageDraftCardProps) {
  const titleId = React.useId()
  const noteId = React.useId()

  const set = <K extends keyof PackageDraft>(key: K, value: PackageDraft[K]) =>
    onChange({ ...draft, [key]: value })

  const complete = missing.length === 0
  // The floor has its own panel and does not hold a package back.
  const blocking = violations.filter((v) => v.field !== "floor_price_cents")
  const published = status === "published"
  const canSave = complete && dirty && pending === null
  const canPublish =
    complete && blocking.length === 0 && pending === null && !published
  const note = !complete
    ? `Still needed: ${missing.map(fieldLabel).join(", ")}`
    : blocking.length > 0 && !published
      ? "Fix the problems above to publish."
      : null
  const stray = violations.filter((v) => !KNOWN_FIELDS.has(v.field))
  const tag = status ?? "new"
  const nicheOptions = NICHES.filter((niche) => niches.includes(niche.value))

  const updateAddon = (index: number, patch: Partial<Addon>) =>
    set(
      "addons",
      draft.addons.map((addon, i) =>
        i === index ? { ...addon, ...patch } : addon
      )
    )
  const without = <T,>(items: readonly T[], index: number) =>
    items.filter((_, i) => i !== index)

  return (
    <section
      aria-labelledby={titleId}
      data-slot="package-draft-card"
      className="rounded-2xl border bg-card text-card-foreground shadow-sm"
    >
      <fieldset
        disabled={pending !== null}
        className="m-0 flex min-w-0 flex-col gap-6 border-0 p-5"
      >
        <header className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <h2 id={titleId} className="font-display text-2xl leading-none">
                Package draft
              </h2>
              <Badge
                variant={tag === "published" ? "secondary" : "outline"}
                className={cn(
                  tag === "published" && "bg-gain/15 text-gain-ink"
                )}
              >
                {STATUS_LABEL[tag]}
              </Badge>
            </div>
            <AnimatedPrice cents={draft.base_price_cents ?? null} />
          </div>
          {onDiscard ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Close"
              onClick={onDiscard}
            >
              <X aria-hidden />
            </Button>
          ) : null}
        </header>

        <Field name="name" text missing={missing} violations={violations}>
          {({ inputId, describedBy, invalid }) => (
            <Input
              id={inputId}
              value={draft.name ?? ""}
              onChange={(event) => set("name", event.target.value)}
              maxLength={100}
              autoComplete="off"
              aria-invalid={invalid ? true : undefined}
              aria-describedby={describedBy}
              className="h-10"
            />
          )}
        </Field>

        <Field name="content_type" missing={missing} violations={violations}>
          {({ labelId, describedBy }) => (
            <ChipGroup<ContentType>
              labelledBy={labelId}
              describedBy={describedBy}
              options={CONTENT_TYPES}
              value={draft.content_type ? [draft.content_type] : []}
              onValueChange={(next) => set("content_type", next[0] ?? null)}
            />
          )}
        </Field>

        <Field name="niche" missing={missing} violations={violations}>
          {({ labelId, describedBy }) => (
            <ChipGroup<Niche>
              labelledBy={labelId}
              describedBy={describedBy}
              options={nicheOptions}
              value={draft.niche ? [draft.niche] : []}
              onValueChange={(next) => set("niche", next[0] ?? null)}
            />
          )}
        </Field>

        <div className="grid gap-6 sm:grid-cols-[auto_1fr]">
          <Field name="volume_count" missing={missing} violations={violations}>
            {({ labelId, describedBy, invalid }) => (
              <Stepper
                labelledBy={labelId}
                describedBy={describedBy}
                invalid={invalid}
                noun="videos"
                min={1}
                value={draft.volume_count ?? null}
                onValueChange={(next) => set("volume_count", next)}
                className="self-start"
              />
            )}
          </Field>
          <Field name="volume_basis" missing={missing} violations={violations}>
            {({ labelId, describedBy }) => (
              <ChipGroup<VolumeBasis>
                labelledBy={labelId}
                describedBy={describedBy}
                options={VOLUME_BASES}
                value={draft.volume_basis ? [draft.volume_basis] : []}
                onValueChange={(next) => set("volume_basis", next[0] ?? null)}
              />
            )}
          </Field>
        </div>

        <Field
          name="base_price_cents"
          text
          missing={missing}
          violations={violations}
        >
          {({ inputId, describedBy, invalid }) => (
            <MoneyInput
              id={inputId}
              value={draft.base_price_cents ?? null}
              onValueChange={(next) => set("base_price_cents", next)}
              aria-invalid={invalid ? true : undefined}
              aria-describedby={describedBy}
              className="h-10"
            />
          )}
        </Field>

        <Field
          name="preferred_channel"
          missing={missing}
          violations={violations}
        >
          {({ labelId, describedBy }) => (
            <ChipGroup<PreferredChannel>
              labelledBy={labelId}
              describedBy={describedBy}
              options={CHANNELS}
              value={draft.preferred_channel ? [draft.preferred_channel] : []}
              onValueChange={(next) =>
                set("preferred_channel", next[0] ?? null)
              }
            />
          )}
        </Field>

        <div className="grid gap-6 sm:grid-cols-2">
          <Field
            name="lead_time_days"
            optional
            missing={missing}
            violations={violations}
          >
            {({ labelId, describedBy, invalid }) => (
              <Stepper
                labelledBy={labelId}
                describedBy={describedBy}
                invalid={invalid}
                noun="lead time"
                unit="days"
                min={1}
                clearable
                value={draft.lead_time_days ?? null}
                onValueChange={(next) => set("lead_time_days", next)}
                className="self-start"
              />
            )}
          </Field>
          <Field
            name="slots_per_month"
            optional
            missing={missing}
            violations={violations}
          >
            {({ labelId, describedBy, invalid }) => (
              <Stepper
                labelledBy={labelId}
                describedBy={describedBy}
                invalid={invalid}
                noun="slots per month"
                min={1}
                clearable
                value={draft.slots_per_month ?? null}
                onValueChange={(next) => set("slots_per_month", next)}
                className="self-start"
              />
            )}
          </Field>
        </div>

        <Field name="addons" optional missing={missing} violations={violations}>
          {({ describedBy }) => (
            <div className="flex flex-col gap-3">
              {draft.addons.length > 0 ? (
                <ul className="flex flex-col gap-3">
                  {draft.addons.map((addon, index) => (
                    <li
                      key={index}
                      className="flex flex-wrap items-center gap-2"
                    >
                      <Input
                        aria-label={`Add-on ${index + 1} name`}
                        aria-describedby={describedBy}
                        value={addon.name}
                        onChange={(event) =>
                          updateAddon(index, { name: event.target.value })
                        }
                        maxLength={100}
                        autoComplete="off"
                        className="h-9 min-w-36 flex-1"
                      />
                      <div className="w-28">
                        <MoneyInput
                          aria-label={`Add-on ${index + 1} price`}
                          aria-describedby={describedBy}
                          value={addon.price_cents || null}
                          onValueChange={(next) =>
                            updateAddon(index, { price_cents: next ?? 0 })
                          }
                          className="h-9"
                        />
                      </div>
                      <div className="w-36">
                        <NativeSelect
                          aria-label={`Add-on ${index + 1} kind`}
                          value={addon.unit}
                          onChange={(event) =>
                            updateAddon(index, {
                              unit: event.target.value as Addon["unit"],
                            })
                          }
                          className="h-9"
                        >
                          <option value="video">Extra video</option>
                          <option value="item">Other item</option>
                        </NativeSelect>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Remove add-on ${addon.name.trim() || index + 1}`}
                        onClick={() =>
                          set("addons", without(draft.addons, index))
                        }
                      >
                        <X aria-hidden />
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : null}
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() =>
                  set("addons", [
                    ...draft.addons,
                    { name: "", price_cents: 0, unit: "video" },
                  ])
                }
              >
                <Plus aria-hidden />
                Add add-on
              </Button>
            </div>
          )}
        </Field>

        {draft.extras.length > 0 ? (
          <TermList
            name="extras"
            noun="extra"
            terms={draft.extras.map(
              (extra) => `${extra.name} · ${formatCents(extra.price_cents)}`
            )}
            onRemove={(index) => set("extras", without(draft.extras, index))}
            missing={missing}
            violations={violations}
          />
        ) : null}
        {draft.included.length > 0 ? (
          <TermList
            name="included"
            noun="included"
            terms={draft.included}
            onRemove={(index) =>
              set("included", without(draft.included, index))
            }
            missing={missing}
            violations={violations}
          />
        ) : null}
        {draft.freebies.length > 0 ? (
          <TermList
            name="freebies"
            noun="freebie"
            terms={draft.freebies}
            onRemove={(index) =>
              set("freebies", without(draft.freebies, index))
            }
            missing={missing}
            violations={violations}
          />
        ) : null}

        <FloorPanel
          baseCents={draft.base_price_cents}
          floorCents={floorCents}
          enabled={status !== null && onFloorSave !== undefined}
          pending={pending !== null}
          violations={violations}
          onSave={(cents) => onFloorSave?.(cents)}
        />

        {stray.length > 0 ? (
          <ul className="flex flex-col gap-0.5">
            {stray.map((violation) => (
              <li
                key={`${violation.field}-${violation.message}`}
                className="text-sm text-destructive"
              >
                {violation.message}
              </li>
            ))}
          </ul>
        ) : null}

        <footer className="flex flex-col gap-3">
          {note ? (
            <p id={noteId} className="text-sm text-muted-foreground">
              {note}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {published ? null : (
              <Button
                type="button"
                size="lg"
                disabled={!canPublish}
                aria-describedby={note ? noteId : undefined}
                onClick={onPublish}
              >
                {pending === "publish" ? (
                  <>
                    <LoaderCircle aria-hidden className="animate-spin" />
                    Publishing…
                  </>
                ) : (
                  "Publish"
                )}
              </Button>
            )}
            <Button
              type="button"
              size="lg"
              variant={published ? "default" : "outline"}
              disabled={!canSave}
              aria-describedby={note ? noteId : undefined}
              onClick={onSave}
            >
              {pending === "save" ? (
                <>
                  <LoaderCircle aria-hidden className="animate-spin" />
                  Saving…
                </>
              ) : published ? (
                "Save changes"
              ) : (
                "Save draft"
              )}
            </Button>
          </div>
        </footer>
      </fieldset>
    </section>
  )
}

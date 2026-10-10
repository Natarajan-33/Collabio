"use client"

import * as React from "react"

import { Input } from "@/components/ui/input"
import { dollarsText, parseDollars } from "@/lib/packages/draft"
import { cn } from "@/lib/utils"

/** Up to seven digits of dollars (under the API's 32-bit cents), then two of cents. */
const AMOUNT = /^\d{0,7}(\.\d{0,2})?$/

type MoneyInputProps = Omit<
  React.ComponentProps<"input">,
  "value" | "defaultValue" | "onChange" | "type"
> & {
  /** The amount in cents, or null for none. */
  value: number | null
  onValueChange: (cents: number | null) => void
}

/**
 * A dollar amount typed as dollars (`999.50`) and held as whole cents. Only characters
 * that belong to an amount are taken, so `$1,200` types as `1200`. While the field is
 * being edited it keeps what was typed (`12.` stays `12.`); once it is left, or the
 * value is changed from elsewhere (by voice, say), it shows the value as a plain amount.
 */
export function MoneyInput({
  value,
  onValueChange,
  className,
  onFocus,
  onBlur,
  ...props
}: MoneyInputProps) {
  const [text, setText] = React.useState(() => dollarsText(value))
  const [editing, setEditing] = React.useState(false)

  if (!editing && text !== dollarsText(value)) setText(dollarsText(value))

  return (
    <div className="relative">
      <span
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-sm text-muted-foreground"
      >
        $
      </span>
      <Input
        {...props}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        value={text}
        onFocus={(event) => {
          setEditing(true)
          onFocus?.(event)
        }}
        onBlur={(event) => {
          setEditing(false)
          setText(dollarsText(parseDollars(text)))
          onBlur?.(event)
        }}
        onChange={(event) => {
          const next = event.target.value.replace(/[$,\s]/g, "")
          if (!AMOUNT.test(next)) return
          setText(next)
          onValueChange(parseDollars(next))
        }}
        className={cn("pl-6 num", className)}
      />
    </div>
  )
}

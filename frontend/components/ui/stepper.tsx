"use client"

import { Minus, Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type StepperProps = {
  /** The count, or null when there is none yet. */
  value: number | null
  onValueChange: (value: number | null) => void
  /** Id of the element that names the stepper (its visible label). */
  labelledBy: string
  /** What the buttons count, in lower case: "videos" gives "Increase videos". */
  noun: string
  /** The lowest count; a stepper never goes below it. Defaults to 0. */
  min?: number
  max?: number
  /** Stepping down from `min` clears the value instead of stopping. */
  clearable?: boolean
  /** Shown while there is no value. */
  emptyText?: string
  /** Shown after the count ("days"). */
  unit?: string
  invalid?: boolean
  /** Id of the element that explains the stepper, such as an error message. */
  describedBy?: string
  className?: string
}

/**
 * A count changed with minus and plus buttons. With no value it reads `emptyText`, and
 * plus starts it at `min`, so nothing is filled in on the user's behalf. The count is a
 * live region, so a screen reader hears each step.
 */
export function Stepper({
  value,
  onValueChange,
  labelledBy,
  noun,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
  clearable = false,
  emptyText = "Not set",
  unit,
  invalid = false,
  describedBy,
  className,
}: StepperProps) {
  const canDecrease = value !== null && (clearable ? true : value > min)
  const canIncrease = value === null || value < max

  function decrease() {
    if (value === null) return
    onValueChange(clearable && value <= min ? null : Math.max(min, value - 1))
  }

  function increase() {
    onValueChange(value === null ? min : Math.min(max, value + 1))
  }

  return (
    <div
      role="group"
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      data-slot="stepper"
      className={cn(
        "inline-flex items-center rounded-lg border border-input",
        invalid && "border-destructive",
        className
      )}
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`Decrease ${noun}`}
        disabled={!canDecrease}
        onClick={decrease}
        className="rounded-r-none"
      >
        <Minus aria-hidden />
      </Button>
      <output
        className={cn(
          "min-w-16 px-2 text-center text-sm",
          value === null ? "text-muted-foreground" : "num"
        )}
      >
        {value === null ? (
          emptyText
        ) : (
          <>
            {value}
            {unit ? (
              <span className="ml-1 text-xs text-muted-foreground">{unit}</span>
            ) : null}
          </>
        )}
      </output>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`Increase ${noun}`}
        disabled={!canIncrease}
        onClick={increase}
        className="rounded-l-none"
      >
        <Plus aria-hidden />
      </Button>
    </div>
  )
}

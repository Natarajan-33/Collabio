"use client"

import { LoaderCircle } from "lucide-react"
import * as React from "react"

import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { components } from "@/lib/api/schema"
import { launchLabel, missingLabels } from "@/lib/brief/state"
import { cn } from "@/lib/utils"

type Policy = components["schemas"]["LaunchRequest"]["follow_up_policy"]
type RuleViolation = components["schemas"]["RuleViolation"]

const POLICIES: readonly { value: Policy; label: string }[] = [
  { value: "off", label: "Off" },
  { value: "suggest", label: "Suggest" },
  { value: "auto", label: "Auto" },
]

type LaunchBarProps = {
  /** How many creators the launch reaches. */
  count: number
  /** Keys of the required fields still empty. */
  missing: readonly string[]
  /** Rules the filled-in fields break. */
  violations: readonly RuleViolation[]
  policy: Policy
  onPolicy: (policy: Policy) => void
  onLaunch: () => void
  /** The launch request is in flight. */
  launching: boolean
  /** Draws the eye to the button, such as when the agent says the brief is ready. */
  pulse?: boolean
}

/** Why Launch is locked, in the order to fix it. Empty when it is not. */
function lockReasons(
  count: number,
  missing: readonly string[],
  violations: readonly RuleViolation[]
): string[] {
  const reasons: string[] = []
  if (missing.length > 0) {
    reasons.push(`Still needed: ${missingLabels(missing).join(", ")}`)
  }
  for (const violation of violations) reasons.push(violation.message)
  if (count === 0) reasons.push("No creators can be contacted.")
  return reasons
}

/**
 * The follow-up policy and the Launch button. Launch stays locked until the brief is
 * complete and breaks no rule, and says what is in the way when it is hovered or focused.
 */
export function LaunchBar({
  count,
  missing,
  violations,
  policy,
  onPolicy,
  onLaunch,
  launching,
  pulse = false,
}: LaunchBarProps) {
  const labelId = React.useId()
  const reasons = lockReasons(count, missing, violations)
  const locked = reasons.length > 0

  const button = (
    <Button
      type="button"
      size="lg"
      disabled={locked || launching}
      onClick={onLaunch}
    >
      {launching ? <LoaderCircle aria-hidden className="animate-spin" /> : null}
      {launchLabel(count)}
    </Button>
  )

  return (
    <div
      data-slot="launch-bar"
      className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-4 rounded-2xl border bg-background/95 p-4 shadow-sm backdrop-blur"
    >
      <div className="flex flex-col gap-1.5">
        <span
          id={labelId}
          className="text-xs tracking-wide text-muted-foreground uppercase"
        >
          Follow-up policy
        </span>
        <ToggleGroup
          aria-labelledby={labelId}
          variant="outline"
          value={[policy]}
          onValueChange={(next) => {
            // Pressing the chosen one again would clear it; a policy is always set.
            const chosen = next[0] as Policy | undefined
            if (chosen) onPolicy(chosen)
          }}
        >
          {POLICIES.map((option) => (
            <ToggleGroupItem
              key={option.value}
              value={option.value}
              className="aria-pressed:border-foreground aria-pressed:bg-foreground aria-pressed:text-background aria-pressed:hover:bg-foreground/90 aria-pressed:hover:text-background"
            >
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <p className="text-xs text-muted-foreground">Follow-ups start in M4.</p>
      </div>

      <Tooltip>
        <TooltipTrigger
          render={
            <span
              tabIndex={locked ? 0 : undefined}
              data-pulse={pulse && !locked ? "true" : undefined}
              className={cn(
                "inline-flex rounded-lg",
                pulse &&
                  !locked &&
                  "ring-2 ring-voice ring-offset-2 motion-safe:animate-pulse"
              )}
            />
          }
        >
          {button}
        </TooltipTrigger>
        {locked ? (
          <TooltipContent className="flex-col items-start" side="top">
            {reasons.map((reason) => (
              <span key={reason}>{reason}</span>
            ))}
          </TooltipContent>
        ) : null}
      </Tooltip>
    </div>
  )
}

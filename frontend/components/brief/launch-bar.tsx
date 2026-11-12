"use client"

import { LoaderCircle } from "lucide-react"
import * as React from "react"

import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { components } from "@/lib/api/schema"
import { launchLabel, missingLabels } from "@/lib/brief/state"
import { cn } from "@/lib/utils"

type Policy = components["schemas"]["LaunchRequest"]["follow_up_policy"]
type RuleViolation = components["schemas"]["RuleViolation"]

type LaunchBarProps = {
  /** How many creators the launch reaches. */
  count: number
  /** Keys of the required fields still empty. */
  missing: readonly string[]
  /** Rules the filled-in fields break. */
  violations: readonly RuleViolation[]
  /** Kept for the caller; follow-ups were never built, so the policy is not shown. */
  policy?: Policy
  onPolicy?: (policy: Policy) => void
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
 * The Launch button (follow-ups were never built, so no follow-up policy is offered; launches
 * keep the default, "off"). Launch stays locked until the brief is
 * complete and breaks no rule, and says what is in the way when it is hovered or focused.
 */
export function LaunchBar({
  count,
  missing,
  violations,
  onLaunch,
  launching,
  pulse = false,
}: LaunchBarProps) {
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
      <p className="text-sm text-muted-foreground">
        Collabio emails each creator your offer; their replies and counters
        appear in Outreach.
      </p>

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

"use client"

import { TriangleAlert } from "lucide-react"

import { CreatorAvatar } from "@/components/deal/creator-avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { components } from "@/lib/api/schema"
import { CALLS_OFF, isHackathon } from "@/lib/hackathon"
import { formatCents } from "@/lib/money"
import { cn } from "@/lib/utils"
import { contentTypeLabel } from "@/lib/vocab"

type Preview = components["schemas"]["BriefCreatorPreview"]
type Delta = components["schemas"]["PackageDelta"]
type ChannelPlan = Preview["default_channel"]

const FLAGS: Record<Delta["flags"][number], { label: string; warn: boolean }> =
  {
    below_base_price: { label: "Below base price", warn: true },
    lead_time_conflict: { label: "Lead time conflict", warn: true },
    estimated: { label: "Estimated", warn: false },
  }

/** Shown on a disabled Call. The backend words the same reason on an excluded creator. */
const NO_PHONE = "No phone opt-in"

function ChannelChoice({
  creator,
  plan,
  onChannel,
}: {
  creator: Preview
  plan: ChannelPlan
  onChannel: (plan: ChannelPlan) => void
}) {
  // Until M4 an email-then-call plan is sent as email, so that is how it reads.
  const current = plan === "call" && !isHackathon ? "call" : "email"

  function choice(value: "email" | "call", disabled: boolean) {
    return (
      <Button
        type="button"
        size="sm"
        variant={current === value ? "default" : "outline"}
        aria-pressed={current === value}
        disabled={disabled}
        onClick={() => {
          if (current !== value) onChannel(value)
        }}
      >
        {value === "email" ? "Email" : "Call"}
      </Button>
    )
  }

  return (
    <div
      role="group"
      aria-label={`How to reach ${creator.name}`}
      className="flex items-center gap-2"
    >
      {choice("email", false)}
      {creator.call_allowed && !isHackathon ? (
        choice("call", false)
      ) : (
        <Tooltip>
          <TooltipTrigger
            render={<span tabIndex={0} className="inline-flex" />}
          >
            {choice("call", true)}
          </TooltipTrigger>
          <TooltipContent>{isHackathon ? CALLS_OFF : NO_PHONE}</TooltipContent>
        </Tooltip>
      )}
    </div>
  )
}

function DeltaSummary({ delta }: { delta: Delta | null }) {
  if (!delta) {
    return (
      <p className="text-sm text-muted-foreground">
        Set the deliverables, opening ask and go-live date to compare.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="num text-sm">{delta.headline}</p>
      <p className="text-xs text-muted-foreground">
        Your ask{" "}
        <span className="num text-foreground">
          {formatCents(delta.ask_per_video_cents)}
        </span>{" "}
        per video, listed{" "}
        <span className="num text-foreground">
          {formatCents(delta.listed_per_video_cents)}
        </span>
      </p>
      {delta.flags.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5">
          {delta.flags.map((flag) => (
            <li key={flag}>
              <Badge variant={FLAGS[flag].warn ? "destructive" : "outline"}>
                {FLAGS[flag].warn ? <TriangleAlert aria-hidden /> : null}
                {FLAGS[flag].label}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

type CreatorsPanelProps = {
  creators: readonly Preview[]
  /** The channel chosen for each creator, by creator id. */
  channels: Readonly<Record<string, ChannelPlan>>
  onChannel: (creatorId: string, plan: ChannelPlan) => void
  /** A creator to draw the eye to, such as one the agent just named. */
  highlighted?: string | null
}

/**
 * The creators the brief goes to: each one's package, how the ask compares with it, and
 * how to reach them. Someone who opted out of contact is greyed out and left off.
 */
export function CreatorsPanel({
  creators,
  channels,
  onChannel,
  highlighted = null,
}: CreatorsPanelProps) {
  if (creators.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed bg-card/60 p-6">
        <h2 className="font-display text-2xl">No creators on this brief</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Pick creators on Discover, then start a brief from the comparison.
        </p>
      </div>
    )
  }

  return (
    <ul aria-label="Creators" className="flex flex-col gap-3">
      {creators.map((creator) => {
        const nameId = `creator-${creator.creator_id}`
        const excluded = creator.excluded_reason !== null
        const isHighlighted = highlighted === creator.creator_id

        return (
          <li
            key={creator.creator_id}
            aria-labelledby={nameId}
            data-excluded={excluded ? "true" : undefined}
            data-highlighted={isHighlighted ? "true" : undefined}
            className={cn(
              "flex flex-col gap-3 rounded-2xl border bg-card p-4 transition-shadow",
              excluded && "opacity-60",
              isHighlighted && "ring-2 ring-voice"
            )}
          >
            <div className="flex items-center gap-3">
              <CreatorAvatar
                initials={creator.initials}
                niches={[creator.package.niche]}
                size="md"
              />
              <div className="min-w-0 flex-1">
                <p id={nameId} className="truncate font-medium">
                  {creator.name}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  @{creator.handle}
                </p>
              </div>
              {excluded ? null : (
                <ChannelChoice
                  creator={creator}
                  plan={channels[creator.creator_id] ?? creator.default_channel}
                  onChannel={(plan) => onChannel(creator.creator_id, plan)}
                />
              )}
            </div>

            <p className="text-sm text-muted-foreground">
              <span className="text-foreground">{creator.package.name}</span>
              {" · "}
              {contentTypeLabel(creator.package.content_type)}
            </p>

            {excluded ? (
              <p className="text-sm text-muted-foreground">
                {creator.excluded_reason}
              </p>
            ) : (
              <DeltaSummary delta={creator.delta} />
            )}
          </li>
        )
      })}
    </ul>
  )
}

"use client"

import { Check } from "lucide-react"
import * as React from "react"

import { CreatorAvatar } from "@/components/deal/creator-avatar"
import { PackageStrip } from "@/components/deal/package-strip"
import { Badge } from "@/components/ui/badge"
import SpotlightCard from "@/components/ui/spotlight-card"
import {
  packageFits,
  type CreatorCard as Creator,
  type SearchFilters,
} from "@/lib/discover/state"
import { formatEngagement, formatFollowers } from "@/lib/format"
import { nicheLabel } from "@/lib/vocab"

type CreatorCardProps = {
  creator: Creator
  /** The filters in force, so packages the search did not ask for can be quieter. */
  filters: SearchFilters
  selected: boolean
  onToggle: (id: string) => void
}

const RESTING_SHADOW =
  "0 1px 2px color-mix(in oklch, var(--foreground) 6%, transparent), 0 14px 32px -22px color-mix(in oklch, var(--foreground) 22%, transparent)"
const SELECTED_SHADOW = `0 0 0 1.5px var(--foreground), ${RESTING_SHADOW}`

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.6875rem] tracking-wide text-muted-foreground uppercase">
        {label}
      </dt>
      <dd className="num text-base font-semibold">{value}</dd>
    </div>
  )
}

/**
 * A creator on the Discover grid: who they are, their reach, and every package they
 * sell with what a video costs. The checkbox puts them in the batch.
 */
export function CreatorCard({
  creator,
  filters,
  selected,
  onToggle,
}: CreatorCardProps) {
  const titleId = React.useId()

  return (
    <SpotlightCard
      theme="light"
      spotlightColor="var(--foreground)"
      intensity={0.14}
      spotlightSize={280}
      role="group"
      aria-labelledby={titleId}
      data-flip-id={creator.id}
      data-selected={selected ? "" : undefined}
      className="h-full rounded-2xl! p-5!"
      style={
        {
          "--spotlight-card-surface": "var(--card)",
          "--spotlight-card-border": selected
            ? "var(--foreground)"
            : "var(--border)",
          "--spotlight-card-shadow": selected
            ? SELECTED_SHADOW
            : RESTING_SHADOW,
        } as React.CSSProperties
      }
    >
      <div className="flex h-full flex-col gap-4">
        <header className="flex items-start gap-3">
          <CreatorAvatar initials={creator.initials} niches={creator.niches} />
          <div className="min-w-0 flex-1 pt-0.5">
            <h3
              id={titleId}
              className="truncate font-display text-xl leading-tight"
            >
              {creator.name}
            </h3>
            <p className="truncate text-sm text-muted-foreground">
              @{creator.handle}
              {creator.region ? ` · ${creator.region}` : null}
            </p>
          </div>

          <label className="relative -mt-1 -mr-1 flex size-9 shrink-0 cursor-pointer items-center justify-center">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggle(creator.id)}
              // A mouse click leaves focus on the box, where Space would toggle it
              // instead of starting a voice command. Keyboard use keeps its focus.
              onClick={(event) => {
                if (event.detail > 0) event.currentTarget.blur()
              }}
              aria-label={`Select ${creator.name}`}
              className="peer absolute inset-0 size-full cursor-pointer opacity-0"
            />
            <span
              aria-hidden
              className="flex size-5 items-center justify-center rounded-md border border-input bg-background text-background transition-colors peer-checked:border-foreground peer-checked:bg-foreground peer-focus-visible:ring-3 peer-focus-visible:ring-ring/50 [&>svg]:opacity-0 peer-checked:[&>svg]:opacity-100"
            >
              <Check className="size-3.5" strokeWidth={3} />
            </span>
          </label>
        </header>

        <dl className="grid grid-cols-2 gap-3">
          <Stat label="Followers" value={formatFollowers(creator.followers)} />
          <Stat
            label="Engagement"
            value={formatEngagement(creator.engagement_rate)}
          />
        </dl>

        {creator.niches.length > 0 ? (
          <ul aria-label="Niches" className="flex flex-wrap gap-1.5">
            {creator.niches.map((niche) => (
              <li key={niche}>
                <Badge variant="outline">{nicheLabel(niche)}</Badge>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="mt-auto flex flex-col gap-2">
          {creator.packages.map((pkg) => (
            <PackageStrip
              key={pkg.id}
              pkg={pkg}
              muted={!packageFits(pkg, filters)}
            />
          ))}
        </div>
      </div>
    </SpotlightCard>
  )
}

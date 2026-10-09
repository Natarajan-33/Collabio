"use client"

import { Check, X } from "lucide-react"
import * as React from "react"

import { CreatorAvatar } from "@/components/deal/creator-avatar"
import { NativeSelect } from "@/components/ui/native-select"
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type {
  CreatorCard as Creator,
  PackageSummary,
} from "@/lib/discover/state"
import { formatCents } from "@/lib/money"
import { cn } from "@/lib/utils"
import { channelLabel, contentTypeLabel } from "@/lib/vocab"

type Prefer = "lowest" | "highest"

/**
 * Which columns hold the best value of a row: the lowest or highest figure, ties
 * included. Nothing is best when fewer than two columns have a figure or they all
 * agree, because a highlight that is everywhere says nothing.
 */
export function bestIndexes(
  values: readonly (number | null)[],
  prefer: Prefer
): Set<number> {
  const known = values.flatMap((value, index) =>
    value === null ? [] : [{ value, index }]
  )
  if (known.length < 2) return new Set()
  const figures = known.map((entry) => entry.value)
  const best = prefer === "lowest" ? Math.min(...figures) : Math.max(...figures)
  if (figures.every((figure) => figure === best)) return new Set()
  return new Set(
    known.filter((entry) => entry.value === best).map((entry) => entry.index)
  )
}

type Row = {
  key: string
  label: string
  /** What the cell shows. */
  show: (pkg: PackageSummary) => string
  /** The figure that is compared, and which way is better. Absent: no "best". */
  compare?: {
    figure: (pkg: PackageSummary) => number | null
    prefer: Prefer
    /** Whether the packages can be compared at all. */
    comparable?: (packages: PackageSummary[]) => boolean
  }
}

const plural = (count: number, unit: string) =>
  `${count} ${unit}${count === 1 ? "" : "s"}`

const ROWS: Row[] = [
  {
    key: "price",
    label: "Price",
    show: (pkg) => formatCents(pkg.base_price_cents),
    compare: { figure: (pkg) => pkg.base_price_cents, prefer: "lowest" },
  },
  {
    key: "per-video",
    label: "Per video",
    show: (pkg) => formatCents(pkg.per_video_cents),
    compare: { figure: (pkg) => pkg.per_video_cents, prefer: "lowest" },
  },
  {
    key: "volume",
    label: "Volume",
    show: (pkg) =>
      `${plural(pkg.volume_count, "video")} / ${pkg.volume_basis === "per_week" ? "week" : "contract"}`,
    compare: {
      figure: (pkg) => pkg.volume_count,
      prefer: "highest",
      // 3 a week and 3 in total are not the same amount of work.
      comparable: (packages) =>
        new Set(packages.map((pkg) => pkg.volume_basis)).size === 1,
    },
  },
  {
    key: "lead-time",
    label: "Lead time",
    show: (pkg) =>
      pkg.lead_time_days === null ? "—" : plural(pkg.lead_time_days, "day"),
    compare: { figure: (pkg) => pkg.lead_time_days, prefer: "lowest" },
  },
  {
    key: "channel",
    label: "Preferred channel",
    show: (pkg) => channelLabel(pkg.preferred_channel),
  },
]

/** The package a column compares: the chosen one if it still exists, else the first. */
export function packageFor(creator: Creator, packageId?: string) {
  return (
    creator.packages.find((pkg) => pkg.id === packageId) ??
    creator.packages[0] ??
    null
  )
}

type CompareTableProps = {
  /** One column each, in order. */
  creators: Creator[]
  /** The package compared for each creator, by creator id. */
  chosen: Record<string, string>
  onChoose: (creatorId: string, packageId: string) => void
  onRemove: (creatorId: string) => void
}

const rowHead =
  "sticky left-0 z-10 w-36 min-w-36 border-b bg-background text-xs font-medium tracking-wide text-muted-foreground uppercase"

function BestMark() {
  return (
    <span className="inline-flex items-center gap-0.5 text-[0.625rem] font-semibold tracking-wider text-gain-ink uppercase">
      <Check aria-hidden className="size-3" strokeWidth={3} />
      Best
      <span className="sr-only"> value in this row</span>
    </span>
  )
}

/**
 * The shortlist side by side: one column per creator, one row per term. In each row the
 * best value carries the gain colour and a "Best" mark, so it does not rest on colour.
 */
export function CompareTable({
  creators,
  chosen,
  onChoose,
  onRemove,
}: CompareTableProps) {
  const packages = creators.map((creator) =>
    packageFor(creator, chosen[creator.id])
  )
  const present = packages.filter((pkg): pkg is PackageSummary => pkg !== null)

  return (
    <Table className="border-separate border-spacing-0">
      <TableCaption className="sr-only">
        Package terms for the {creators.length} selected creators. The best
        value in each row is marked.
      </TableCaption>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead scope="col" className={cn(rowHead, "align-bottom")}>
            Creator
          </TableHead>
          {creators.map((creator) => (
            <TableHead
              key={creator.id}
              scope="col"
              className="h-auto min-w-52 border-b py-3 align-top"
            >
              <div className="flex items-start gap-2.5">
                <CreatorAvatar
                  size="md"
                  initials={creator.initials}
                  niches={creator.niches}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-display text-lg leading-tight">
                    {creator.name}
                  </p>
                  <p className="truncate text-xs font-normal text-muted-foreground">
                    @{creator.handle}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onRemove(creator.id)}
                  aria-label={`Remove ${creator.name} from the comparison`}
                  className="-mt-0.5 -mr-1 flex size-7 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <X aria-hidden className="size-4" />
                </button>
              </div>
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>

      <TableBody>
        <TableRow className="hover:bg-transparent">
          <TableHead scope="row" className={cn(rowHead, "align-top")}>
            Package
          </TableHead>
          {creators.map((creator, column) => {
            const pkg = packages[column]
            return (
              <TableCell
                key={creator.id}
                className="border-b align-top whitespace-normal"
              >
                {pkg === null ? (
                  <span className="text-muted-foreground">No packages</span>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    {creator.packages.length > 1 ? (
                      <NativeSelect
                        aria-label={`Package for ${creator.name}`}
                        value={pkg.id}
                        onChange={(event) =>
                          onChoose(creator.id, event.target.value)
                        }
                      >
                        {creator.packages.map((option) => (
                          <option key={option.id} value={option.id}>
                            {option.name}
                          </option>
                        ))}
                      </NativeSelect>
                    ) : (
                      <span className="font-medium">{pkg.name}</span>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {contentTypeLabel(pkg.content_type)}
                    </span>
                  </div>
                )}
              </TableCell>
            )
          })}
        </TableRow>

        {ROWS.map((row) => {
          const compare = row.compare
          const best =
            compare && (compare.comparable?.(present) ?? true)
              ? bestIndexes(
                  packages.map((pkg) => (pkg ? compare.figure(pkg) : null)),
                  compare.prefer
                )
              : new Set<number>()

          return (
            <TableRow key={row.key} className="hover:bg-transparent">
              <TableHead scope="row" className={rowHead}>
                {row.label}
              </TableHead>
              {creators.map((creator, column) => {
                const pkg = packages[column]
                const isBest = best.has(column)
                return (
                  <TableCell
                    key={creator.id}
                    data-best={isBest ? "" : undefined}
                    className={cn(
                      "border-b py-3",
                      isBest && "bg-gain/10 font-semibold text-gain-ink"
                    )}
                  >
                    {pkg === null ? (
                      "—"
                    ) : (
                      <span className="flex items-center gap-2">
                        <span className="num">{row.show(pkg)}</span>
                        {isBest ? <BestMark /> : null}
                      </span>
                    )}
                  </TableCell>
                )
              })}
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

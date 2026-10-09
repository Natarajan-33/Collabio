"use client"

import { Plus, X } from "lucide-react"
import * as React from "react"

import { ChipGroup } from "@/components/auth/chip-group"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  chipsFor,
  normalizeFilters,
  type FilterChip,
  type SearchFilters,
} from "@/lib/discover/state"
import { formatCents } from "@/lib/money"
import { CONTENT_TYPES, NICHES } from "@/lib/vocab"

/** The price caps offered in the popover. Voice can set any amount. */
const PRICE_CAPS = [50_000, 100_000, 200_000, 500_000] as const

const PRICE_OPTIONS = PRICE_CAPS.map((cents) => ({
  value: String(cents),
  label: `Up to ${formatCents(cents)}`,
}))

/** Chips whose label is a number or an amount read best in the figure face. */
const NUMERIC: ReadonlySet<FilterChip["kind"]> = new Set([
  "max_price",
  "min_followers",
])

type FilterChipsProps = {
  filters: SearchFilters
  /** One chip was taken off. */
  onRemove: (chip: FilterChip) => void
  /** The popover changed the filters. */
  onFiltersChange: (filters: SearchFilters) => void
}

function Group({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-2">
      <h3
        id={id}
        className="font-sans text-xs font-medium tracking-wide text-muted-foreground uppercase"
      >
        {title}
      </h3>
      {children}
    </section>
  )
}

function AddFilter({
  filters,
  onFiltersChange,
}: Pick<FilterChipsProps, "filters" | "onFiltersChange">) {
  const id = React.useId()
  const cap = filters.max_price_cents

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="outline"
            className="h-8 rounded-full border-dashed px-3"
          />
        }
      >
        <Plus aria-hidden />
        Add filter
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(24rem,calc(100vw-2rem))]">
        <Group id={`${id}-niche`} title="Niche">
          <ChipGroup
            labelledBy={`${id}-niche`}
            options={NICHES}
            multiple
            value={filters.niches}
            onValueChange={(niches) =>
              onFiltersChange(normalizeFilters({ ...filters, niches }))
            }
          />
        </Group>
        <Group id={`${id}-format`} title="Format">
          <ChipGroup
            labelledBy={`${id}-format`}
            options={CONTENT_TYPES}
            multiple
            value={filters.content_types}
            onValueChange={(content_types) =>
              onFiltersChange(normalizeFilters({ ...filters, content_types }))
            }
          />
        </Group>
        <Group id={`${id}-price`} title="Price">
          <ChipGroup
            labelledBy={`${id}-price`}
            options={PRICE_OPTIONS}
            value={cap ? [String(cap)] : []}
            onValueChange={([picked]) =>
              onFiltersChange(
                normalizeFilters({
                  ...filters,
                  max_price_cents: picked ? Number(picked) : null,
                })
              )
            }
          />
        </Group>
      </PopoverContent>
    </Popover>
  )
}

/**
 * What the search is filtered by, one chip per filter, each with a one-tap remove. The
 * chips light up as a spoken search is understood, and can be edited by hand: remove
 * one, or add a niche, format or price cap from the popover.
 */
export function FilterChips({
  filters,
  onRemove,
  onFiltersChange,
}: FilterChipsProps) {
  const chips = chipsFor(filters)

  return (
    <div
      role="group"
      aria-label="Search filters"
      className="flex flex-wrap items-center gap-2"
    >
      {chips.map((chip) => (
        <span
          key={chip.id}
          data-slot="filter-chip"
          className="inline-flex h-8 items-center gap-0.5 rounded-full bg-foreground pr-1 pl-3.5 text-sm font-medium text-background"
        >
          <span className={NUMERIC.has(chip.kind) ? "num" : undefined}>
            {chip.label}
          </span>
          <button
            type="button"
            onClick={() => onRemove(chip)}
            aria-label={`Remove filter ${chip.label}`}
            className="flex size-6 items-center justify-center rounded-full text-background/70 outline-none hover:bg-background/15 hover:text-background focus-visible:ring-3 focus-visible:ring-ring/60"
          >
            <X aria-hidden className="size-3.5" />
          </button>
        </span>
      ))}
      <AddFilter filters={filters} onFiltersChange={onFiltersChange} />
      {chips.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No filters yet. Say what you are looking for, or add one.
        </p>
      ) : null}
    </div>
  )
}

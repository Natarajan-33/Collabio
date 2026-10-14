import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatDay } from "@/lib/deal/terms"
import { formatCents } from "@/lib/money"
import type { components } from "@/lib/api/schema"
import { cn } from "@/lib/utils"

type TermsColumn = components["schemas"]["TermsColumn"]

const DASH = <span className="text-muted-foreground">—</span>

type RowSpec = {
  key: string
  label: string
  /** The deal fields (as the API names them in `changed`) this row shows. */
  fields: readonly string[]
  cell: (column: TermsColumn) => React.ReactNode
}

const ROWS: readonly RowSpec[] = [
  {
    key: "videos",
    label: "Videos",
    fields: ["videos"],
    cell: (c) =>
      c.videos == null ? DASH : <span className="num">{c.videos}</span>,
  },
  {
    key: "price",
    label: "Price",
    fields: ["price_cents"],
    cell: (c) =>
      c.price_cents == null ? (
        DASH
      ) : (
        <span className="num">{formatCents(c.price_cents)}</span>
      ),
  },
  {
    key: "per_video",
    label: "$/video",
    fields: ["videos", "price_cents"],
    cell: (c) =>
      c.per_video_cents == null ? (
        DASH
      ) : (
        <span className="num">{formatCents(c.per_video_cents)}</span>
      ),
  },
  {
    key: "go_live",
    label: "Go-live",
    fields: ["go_live_by"],
    cell: (c) =>
      c.go_live_by == null ? (
        DASH
      ) : (
        <span className="num">{formatDay(c.go_live_by)}</span>
      ),
  },
  {
    key: "conditions",
    label: "Conditions",
    fields: ["conditions"],
    cell: (c) =>
      c.conditions.length === 0 ? (
        <span className="text-muted-foreground">None</span>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {c.conditions.map((text, index) => (
            <li key={`${text}-${index}`}>{text}</li>
          ))}
        </ul>
      ),
  },
]

export type CompareColumnsProps = {
  /** The creator's own package, or null when there is none to show. */
  mine: TermsColumn | null
  /** The brand's ask. */
  theirs: TermsColumn
  /** The latest position, or null before there is one. */
  latest: TermsColumn | null
  /** Deal fields that differ between the asks and the latest (the API's `changed`). */
  changed: readonly string[]
  /** Column headings; the default suits the creator's offer desk. */
  labels?: readonly [string, string, string]
}

/**
 * Positions side by side: videos, price, price per video, go-live date and conditions,
 * one column each for the package, the ask and the latest counter. A row whose figure
 * moved (`changed`) is tinted and carries `data-changed="true"`, and says so for screen
 * readers too. A column with nothing to show is left out.
 */
export function CompareColumns({
  mine,
  theirs,
  latest,
  changed,
  labels = ["My package", "Their ask", "Latest"],
}: CompareColumnsProps) {
  const columns = [
    { label: labels[0], terms: mine },
    { label: labels[1], terms: theirs as TermsColumn | null },
    { label: labels[2], terms: latest },
  ].filter(
    (column): column is { label: string; terms: TermsColumn } =>
      column.terms !== null
  )

  return (
    <Table data-slot="compare-columns">
      <TableHeader>
        <TableRow>
          <TableHead>
            <span className="sr-only">Term</span>
          </TableHead>
          {columns.map((column) => (
            <TableHead key={column.label}>{column.label}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {ROWS.map((row) => {
          const isChanged = row.fields.some((field) => changed.includes(field))
          return (
            <TableRow
              key={row.key}
              data-changed={isChanged ? "true" : undefined}
              className={cn(isChanged && "bg-muted/60")}
            >
              <TableCell className="font-medium text-muted-foreground">
                {row.label}
                {isChanged ? <span className="sr-only"> (changed)</span> : null}
              </TableCell>
              {columns.map((column) => (
                <TableCell key={column.label} className="whitespace-normal">
                  {row.cell(column.terms)}
                </TableCell>
              ))}
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

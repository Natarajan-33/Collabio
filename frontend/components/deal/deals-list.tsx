"use client"

import Link from "next/link"
import * as React from "react"

import { StatusPill } from "@/components/board/status-pill"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { formatDay } from "@/lib/deal/terms"
import { formatCents } from "@/lib/money"

type DealListItem = components["schemas"]["DealListItem"]

type Viewer = "brand" | "creator"

const COPY: Record<Viewer, { counterpart: string; empty: string }> = {
  brand: {
    counterpart: "Creator",
    empty:
      "No booked deals yet. Award a creator from a launch board to book one.",
  },
  creator: {
    counterpart: "Brand",
    empty: "No booked deals yet. Accepted offers that a brand books appear here.",
  },
}

/**
 * The deals that have been booked, newest first as the API sends them. Each row is the
 * other side, the product, and what was agreed; it opens the deal.
 */
export function DealsList({ viewer }: { viewer: Viewer }) {
  const api = useApi()
  const [items, setItems] = React.useState<DealListItem[] | null>(null)
  const [failed, setFailed] = React.useState(false)

  React.useEffect(() => {
    let gone = false
    void (async () => {
      try {
        const { data } = await api.GET("/api/v1/deals")
        if (gone) return
        if (data) setItems(data)
        else setFailed(true)
      } catch {
        if (!gone) setFailed(true)
      }
    })()
    return () => {
      gone = true
    }
  }, [api])

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Deals</h1>
        <p className="text-sm text-muted-foreground">
          {viewer === "brand"
            ? "Creators you have booked, and what you agreed."
            : "Offers that were booked, and what was agreed."}
        </p>
      </div>

      {failed ? (
        <p className="text-sm text-destructive">Could not load your deals.</p>
      ) : items === null ? (
        <p className="text-sm text-muted-foreground">Loading deals…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{COPY[viewer].empty}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((deal) => (
            <li key={deal.id}>
              <Link
                href={`/${viewer}/deals/${deal.id}`}
                data-slot="deal-row"
                className="grid gap-x-6 gap-y-2 rounded-xl border bg-card px-4 py-3 text-card-foreground outline-none transition-colors hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1.6fr)_auto] sm:items-center"
              >
                <span className="flex min-w-0 flex-col">
                  <span className="truncate font-medium">
                    {deal.counterpart_name}
                  </span>
                  <span className="truncate text-sm text-muted-foreground">
                    {deal.product_name}
                  </span>
                </span>
                <span className="flex flex-wrap items-baseline gap-x-3 text-sm">
                  <span className="num">
                    {deal.videos} {deal.videos === 1 ? "video" : "videos"}
                  </span>
                  <span className="num font-medium">
                    {formatCents(deal.price_cents)}
                  </span>
                  <span className="num text-muted-foreground">
                    live by {formatDay(deal.go_live_by)}
                  </span>
                </span>
                <span className="flex items-center sm:justify-end">
                  <StatusPill status="awarded" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

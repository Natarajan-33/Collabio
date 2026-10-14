"use client"

import { ArrowLeft } from "lucide-react"
import Link from "next/link"
import * as React from "react"

import { StatusPill } from "@/components/board/status-pill"
import { DealSummary } from "@/components/deal/deal-summary"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"

type DealView = components["schemas"]["DealView"]

type Viewer = "brand" | "creator"

/** One booked deal: what was agreed, the payment schedule and how to reach the other side. */
export function DealDetail({
  viewer,
  dealId,
}: {
  viewer: Viewer
  dealId: string
}) {
  const api = useApi()
  const [deal, setDeal] = React.useState<DealView | null>(null)
  const [failed, setFailed] = React.useState(false)
  const listPath = `/${viewer}/deals`

  React.useEffect(() => {
    let gone = false
    void (async () => {
      try {
        const { data } = await api.GET("/api/v1/deals/{deal_id}", {
          params: { path: { deal_id: dealId } },
        })
        if (gone) return
        if (data) setDeal(data)
        else setFailed(true)
      } catch {
        if (!gone) setFailed(true)
      }
    })()
    return () => {
      gone = true
    }
  }, [api, dealId])

  const back = (
    <Link
      href={listPath}
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft aria-hidden className="size-3.5" />
      All deals
    </Link>
  )

  if (failed) {
    return (
      <div className="mx-auto max-w-3xl space-y-3 p-6">
        {back}
        <p className="text-sm text-destructive">Could not load this deal.</p>
      </div>
    )
  }

  if (deal === null) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading deal…</div>
    )
  }

  const counterpart = viewer === "brand" ? deal.creator : deal.brand
  const negotiation =
    viewer === "brand"
      ? {
          href: `/brand/batches/${deal.batch_id}?thread=${deal.thread_id}`,
          label: "View negotiation",
        }
      : { href: `/creator/offers/${deal.thread_id}`, label: "View offer" }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="space-y-2">
        {back}
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            {deal.product_name}
            <span className="text-muted-foreground"> · {counterpart.name}</span>
          </h1>
          <StatusPill status="awarded" />
        </div>
        <Link
          href={negotiation.href}
          className="w-fit text-sm underline underline-offset-4"
        >
          {negotiation.label}
        </Link>
      </div>

      <DealSummary deal={deal} viewer={viewer} />
    </div>
  )
}

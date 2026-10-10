"use client"

import Link from "next/link"
import * as React from "react"

import { buttonVariants } from "@/components/ui/button"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { launchedAgo } from "@/lib/board/state"

type BatchListItem = components["schemas"]["BatchListItem"]

export default function BatchesPage() {
  const api = useApi()
  const [items, setItems] = React.useState<BatchListItem[]>([])
  const [phase, setPhase] = React.useState<"loading" | "ready" | "failed">(
    "loading"
  )
  const now = React.useMemo(() => new Date(), [])

  React.useEffect(() => {
    let cancelled = false
    void (async () => {
      const { data, error } = await api.GET("/api/v1/batches")
      if (cancelled) return
      if (error || !data) {
        setPhase("failed")
        return
      }
      setItems(data)
      setPhase("ready")
    })()
    return () => {
      cancelled = true
    }
  }, [api])

  if (phase === "loading") {
    return (
      <div className="p-6 text-muted-foreground text-sm">Loading launches…</div>
    )
  }

  if (phase === "failed") {
    return (
      <div className="p-6 text-destructive text-sm">
        Could not load your launches.
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 p-12 text-center">
        <p className="text-muted-foreground">
          No launches yet. Pick creators on Discover and start a negotiation.
        </p>
        <Link href="/brand/discover" className={buttonVariants()}>
          Go to Discover
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl p-6">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Board</h1>
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">Product</th>
              <th className="px-4 py-3 font-medium">Launched</th>
              <th className="num px-4 py-3 font-medium">Threads</th>
              <th className="num px-4 py-3 font-medium">Contacted</th>
              <th className="num px-4 py-3 font-medium">Replied</th>
              <th className="num px-4 py-3 font-medium">Countered</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id} className="border-b last:border-0">
                <td className="px-4 py-3">
                  <Link
                    href={`/brand/batches/${row.id}`}
                    className="font-medium text-voice hover:underline"
                  >
                    {row.product_name}
                  </Link>
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {launchedAgo(row.launched_at, now)}
                </td>
                <td className="num px-4 py-3 tabular-nums">{row.thread_count}</td>
                <td className="num px-4 py-3 tabular-nums">{row.contacted}</td>
                <td className="num px-4 py-3 tabular-nums">{row.replied}</td>
                <td className="num px-4 py-3 tabular-nums">{row.countered}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

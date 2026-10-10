"use client"

import * as React from "react"

import CountUp from "@/components/ui/count-up"
import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"
import { launchedAgo } from "@/lib/board/state"

type BatchKpis = components["schemas"]["BatchKpis"]

export function KpiStrip({
  kpis,
  now,
}: {
  kpis: BatchKpis
  now: Date
}) {
  const [, bump] = React.useReducer((n) => n + 1, 0)

  React.useEffect(() => {
    const tick = setInterval(() => bump(), 30_000)
    return () => clearInterval(tick)
  }, [])

  const sinceLaunch = launchedAgo(kpis.launched_at, now)

  return (
    <div className="flex flex-wrap items-end gap-x-8 gap-y-3 text-sm">
      <Kpi label="Contacted" value={kpis.contacted} />
      <Kpi label="Replied" value={kpis.replied} />
      <Kpi label="Countered" value={kpis.countered} />
      <div>
        <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
          Best $/video
        </p>
        <p className="num text-lg font-semibold tabular-nums">
          {kpis.best_per_video_cents != null
            ? formatCents(kpis.best_per_video_cents)
            : "—"}
        </p>
      </div>
      <div>
        <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
          Since launch
        </p>
        <p className="text-sm font-medium">{sinceLaunch}</p>
      </div>
    </div>
  )
}

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
        {label}
      </p>
      <p className="num text-lg font-semibold tabular-nums">
        <CountUp to={value} />
      </p>
    </div>
  )
}

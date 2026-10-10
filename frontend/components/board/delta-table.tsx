import type { components } from "@/lib/api/schema"
import { formatCents } from "@/lib/money"

type PackageDelta = components["schemas"]["PackageDelta"]

function cell(value: string | number | null): string {
  if (value === null || value === undefined) return "—"
  return String(value)
}

export function DeltaTable({ delta }: { delta: PackageDelta }) {
  const rows = [
    {
      label: "Videos",
      listed: delta.listed_videos,
      ask: delta.ask_videos,
      latest: delta.latest_videos,
    },
    {
      label: "Price",
      listed: formatCents(delta.listed_price_cents),
      ask: formatCents(delta.ask_price_cents),
      latest:
        delta.latest_price_cents != null
          ? formatCents(delta.latest_price_cents)
          : null,
    },
    {
      label: "$/video",
      listed: formatCents(delta.listed_per_video_cents),
      ask: formatCents(delta.ask_per_video_cents),
      latest:
        delta.latest_per_video_cents != null
          ? formatCents(delta.latest_per_video_cents)
          : null,
    },
    {
      label: "Go-live window",
      listed:
        delta.lead_time_days != null
          ? `${delta.lead_time_days} d lead`
          : "—",
      ask: `${delta.days_to_go_live} d to go-live`,
      latest: "—",
    },
  ]

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-muted-foreground text-xs">
          <th className="pb-2 text-left font-medium" />
          <th className="num pb-2 text-right font-medium">Listed</th>
          <th className="num pb-2 text-right font-medium">Ask</th>
          <th className="num pb-2 text-right font-medium">Latest</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label} className="border-t">
            <td className="py-2 font-medium">{row.label}</td>
            <td className="num py-2 text-right tabular-nums">
              {cell(row.listed)}
            </td>
            <td className="num py-2 text-right tabular-nums">{cell(row.ask)}</td>
            <td className="num py-2 text-right tabular-nums">
              {cell(row.latest)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

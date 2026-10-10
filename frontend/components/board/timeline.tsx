import type { components } from "@/lib/api/schema"
import { eventLabel, lastEventLine } from "@/lib/board/state"

type ThreadEventView = components["schemas"]["ThreadEventView"]

export function Timeline({
  events,
  now,
}: {
  events: ThreadEventView[]
  now: Date
}) {
  const sorted = [...events].sort(
    (a, b) => b.created_at.localeCompare(a.created_at)
  )
  return (
    <ol className="space-y-2 text-sm">
      {sorted.map((event) => (
        <li key={event.id} className="flex justify-between gap-3">
          <span>{eventLabel(event.type)}</span>
          <span className="text-muted-foreground text-xs shrink-0">
            {lastEventLine(event, now).split(" · ").slice(1).join(" · ") ||
              lastEventLine(event, now)}
          </span>
        </li>
      ))}
    </ol>
  )
}

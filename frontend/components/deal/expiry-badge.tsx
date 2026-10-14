import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** How long is left, in its largest whole unit: `3d`, `5h` or `12m`; null once it is over. */
function remaining(ms: number): string | null {
  if (ms <= 0) return null
  if (ms >= DAY) return `${Math.floor(ms / DAY)}d`
  if (ms >= HOUR) return `${Math.floor(ms / HOUR)}h`
  return `${Math.max(1, Math.floor(ms / MINUTE))}m`
}

/**
 * When an offer lapses: "expires in 3d", "expires in 5h", "expired". `now` is passed in
 * so the badge stays a pure function of its props (and so a page controls its clock).
 * Under a day left it takes the warning colour; once over it goes quiet. Nothing is drawn for an offer that does
 * not expire.
 */
export function ExpiryBadge({
  expiresAt,
  now,
}: {
  expiresAt: string | null
  now: Date
}) {
  if (!expiresAt) return null
  const ms = new Date(expiresAt).getTime() - now.getTime()
  const left = remaining(ms)
  const urgent = left !== null && ms < DAY

  return (
    <Badge
      variant={urgent ? "destructive" : "outline"}
      data-slot="expiry-badge"
      data-urgent={urgent ? "true" : undefined}
      className={cn(left === null && "text-muted-foreground")}
    >
      {left === null ? (
        "expired"
      ) : (
        <>
          expires in <span className="num">{left}</span>
        </>
      )}
    </Badge>
  )
}

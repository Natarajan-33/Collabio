import type { components } from "@/lib/api/schema"
import { STATUS_LABEL, STATUS_TONE } from "@/lib/board/state"
import { cn } from "@/lib/utils"

type ThreadStatus = components["schemas"]["ThreadCard"]["status"]

const TONE_CLASS: Record<
  (typeof STATUS_TONE)[ThreadStatus],
  string
> = {
  neutral: "bg-muted text-muted-foreground",
  active: "bg-voice/15 text-voice",
  positive: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  negative: "bg-destructive/15 text-destructive",
  attention: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
}

export function StatusPill({ status }: { status: ThreadStatus }) {
  const tone = STATUS_TONE[status]
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2 py-0.5 text-[0.6875rem] font-medium leading-tight",
        TONE_CLASS[tone]
      )}
    >
      {STATUS_LABEL[status]}
    </span>
  )
}

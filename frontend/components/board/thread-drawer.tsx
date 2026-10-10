"use client"

import * as React from "react"

import { DeltaTable } from "@/components/board/delta-table"
import { StatusPill } from "@/components/board/status-pill"
import { Timeline } from "@/components/board/timeline"
import { TranscriptView } from "@/components/board/transcript-view"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { termsLine } from "@/lib/board/state"

type ThreadDetail = components["schemas"]["ThreadDetail"]

export function ThreadDrawer({
  threadId,
  onClose,
  refreshKey,
  onRetry,
}: {
  threadId: string | null
  onClose: () => void
  refreshKey: number
  onRetry: (threadId: string) => void
}) {
  const api = useApi()
  const [detail, setDetail] = React.useState<ThreadDetail | null>(null)
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({})
  const now = new Date()

  React.useEffect(() => {
    if (!threadId) return
    let gone = false
    void (async () => {
      const { data, error } = await api.GET("/api/v1/threads/{thread_id}", {
        params: { path: { thread_id: threadId } },
      })
      if (!gone && data && !error) setDetail(data)
    })()
    return () => {
      gone = true
    }
  }, [api, threadId, refreshKey])

  const card = detail?.card

  return (
    <Sheet
      open={threadId !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <SheetContent
        side="right"
        className="w-full overflow-y-auto sm:max-w-[480px]"
      >
        {card ? (
          <>
            <SheetHeader>
              <SheetTitle className="flex flex-wrap items-center gap-2">
                {card.creator.name}
                <StatusPill status={card.status} />
                <span className="text-muted-foreground text-xs font-normal capitalize">
                  {card.channel_plan.replace("_", " ")}
                </span>
              </SheetTitle>
            </SheetHeader>

            <section className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Terms
              </h3>
              <p className="num text-sm tabular-nums">
                {termsLine(card.latest_terms)}
              </p>
            </section>

            <section className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Compared with their package
              </h3>
              <DeltaTable delta={card.delta} />
              {card.delta.flags.length ? (
                <ul className="text-xs text-amber-700 dark:text-amber-300">
                  {card.delta.flags.map((flag) => (
                    <li key={flag}>{flag.replaceAll("_", " ")}</li>
                  ))}
                </ul>
              ) : null}
            </section>

            <section className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Timeline
              </h3>
              <Timeline events={detail?.events ?? []} now={now} />
            </section>

            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Transcripts
              </h3>
              {(detail?.transcripts ?? []).map((tr) => (
                <div key={tr.id} className="rounded-lg border p-3">
                  <button
                    type="button"
                    className="text-left text-sm font-medium w-full"
                    onClick={() =>
                      setExpanded((prev) => ({
                        ...prev,
                        [tr.id]: !prev[tr.id],
                      }))
                    }
                  >
                    {tr.kind === "email_out" ? "Drafted email" : "Call"}{" "}
                    <span className="text-muted-foreground text-xs">
                      {expanded[tr.id] ? "Hide" : "Show"}
                    </span>
                  </button>
                  {expanded[tr.id] ? (
                    <div className="mt-2">
                      <TranscriptView transcript={tr} />
                    </div>
                  ) : null}
                </div>
              ))}
            </section>

            <section className="space-y-2 border-t pt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Actions
              </h3>
              {card.status === "failed" ? (
                <Button
                  type="button"
                  size="sm"
                  onClick={() => onRetry(card.id)}
                >
                  Retry
                </Button>
              ) : null}
              {["Counter by voice", "Award", "Decline"].map((label) => (
                <Tooltip key={label}>
                  <TooltipTrigger
                    render={
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled
                        className="mr-2"
                      />
                    }
                  >
                    {label}
                  </TooltipTrigger>
                  <TooltipContent>Coming in M3</TooltipContent>
                </Tooltip>
              ))}
            </section>
          </>
        ) : (
          <p className="text-muted-foreground text-sm p-4">Loading thread…</p>
        )}
      </SheetContent>
    </Sheet>
  )
}

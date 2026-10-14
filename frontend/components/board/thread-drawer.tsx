"use client"

import * as React from "react"

import { AwardDialog } from "@/components/board/award-dialog"
import { CounterDialog } from "@/components/board/counter-dialog"
import { DeclineDialog } from "@/components/board/decline-dialog"
import { DeltaTable } from "@/components/board/delta-table"
import { ResolveDialog } from "@/components/board/resolve-dialog"
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
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { type BoardDialog, termsLine } from "@/lib/board/state"
import type { TermsDraft } from "@/lib/deal/terms"

type ThreadDetail = components["schemas"]["ThreadDetail"]
type ThreadCard = components["schemas"]["ThreadCard"]
type BriefSummary = components["schemas"]["BriefSummary"]
type BrandAction = ThreadCard["allowed_actions"][number]

/** The buttons, in the order they read: the decisive ones first. */
const ACTIONS: { action: BrandAction; label: string }[] = [
  { action: "award", label: "Award" },
  { action: "counter", label: "Counter" },
  { action: "resolve", label: "Resolve" },
  { action: "decline", label: "Decline" },
  { action: "withdraw", label: "Withdraw" },
  { action: "retry", label: "Retry" },
]

export function ThreadDrawer({
  threadId,
  brief,
  onClose,
  refreshKey,
  onRetry,
  dialog,
  onOpenDialog,
  onCloseDialog,
  counterDraft,
  onCounterDraftChange,
  onChanged,
}: {
  threadId: string | null
  /** The batch's brief: the ask a reply is measured against. */
  brief: BriefSummary
  onClose: () => void
  refreshKey: number
  onRetry: (threadId: string) => void
  /** Which confirming dialog is open. The board owns it, so voice can open one. */
  dialog: BoardDialog | null
  onOpenDialog: (dialog: BoardDialog, card: ThreadCard) => void
  onCloseDialog: () => void
  /** The counter being edited, also owned by the board. */
  counterDraft: TermsDraft
  onCounterDraftChange: (draft: TermsDraft) => void
  /** An action went through, or the thread moved under it: the board loads again. */
  onChanged: () => void
}) {
  const api = useApi()
  const [detail, setDetail] = React.useState<ThreadDetail | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({})
  const now = new Date()

  React.useEffect(() => {
    if (!threadId) return
    let gone = false
    void (async () => {
      const { data, error } = await api.GET("/api/v1/threads/{thread_id}", {
        params: { path: { thread_id: threadId } },
      })
      if (gone) return
      if (data && !error) {
        setDetail(data)
        setFailed(false)
      } else {
        setFailed(true)
      }
    })()
    return () => {
      gone = true
    }
  }, [api, threadId, refreshKey])

  // A detail left over from the last thread is not this one's.
  const card = detail?.card.id === threadId ? detail.card : undefined

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
                    {tr.kind === "email_out"
                      ? "Drafted email"
                      : tr.kind === "email_in"
                        ? "Reply received"
                        : "Call"}{" "}
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

            {card.allowed_actions.length > 0 ? (
              <section className="space-y-2 border-t pt-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Actions
                </h3>
                <div className="flex flex-wrap gap-2">
                  {ACTIONS.filter(({ action }) =>
                    card.allowed_actions.includes(action)
                  ).map(({ action, label }) => (
                    <Button
                      key={action}
                      type="button"
                      size="sm"
                      variant={action === "award" ? "default" : "outline"}
                      onClick={() =>
                        action === "retry"
                          ? onRetry(card.id)
                          : onOpenDialog(action, card)
                      }
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              </section>
            ) : null}

            <AwardDialog
              threadId={card.id}
              creatorName={card.creator.name}
              open={dialog === "award"}
              onOpenChange={(open) => {
                if (!open) onCloseDialog()
              }}
              onAwarded={onChanged}
              onStale={onChanged}
            />
            <CounterDialog
              card={card}
              open={dialog === "counter"}
              onClose={onCloseDialog}
              draft={counterDraft}
              onDraftChange={onCounterDraftChange}
              onChanged={onChanged}
            />
            <ResolveDialog
              card={card}
              brief={brief}
              events={detail?.events ?? []}
              transcripts={detail?.transcripts ?? []}
              open={dialog === "resolve"}
              onClose={onCloseDialog}
              onChanged={onChanged}
            />
            <DeclineDialog
              card={card}
              action="decline"
              open={dialog === "decline"}
              onClose={onCloseDialog}
              onChanged={onChanged}
            />
            <DeclineDialog
              card={card}
              action="withdraw"
              open={dialog === "withdraw"}
              onClose={onCloseDialog}
              onChanged={onChanged}
            />
          </>
        ) : (
          <p
            className={
              failed
                ? "text-destructive text-sm p-4"
                : "text-muted-foreground text-sm p-4"
            }
          >
            {failed ? "Could not load this thread." : "Loading thread…"}
          </p>
        )}
      </SheetContent>
    </Sheet>
  )
}

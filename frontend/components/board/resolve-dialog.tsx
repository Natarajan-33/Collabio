"use client"

import * as React from "react"
import { toast } from "sonner"

import { TranscriptView } from "@/components/board/transcript-view"
import { TermsCard } from "@/components/deal/terms-card"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { GENERIC_ERROR, reportActionError } from "@/lib/board/action-error"
import { termsToDraft } from "@/lib/board/state"
import { draftToInput, termsSummary, type TermsDraft } from "@/lib/deal/terms"

type ThreadCard = components["schemas"]["ThreadCard"]
type ThreadEventView = components["schemas"]["ThreadEventView"]
type TranscriptViewModel = components["schemas"]["TranscriptView"]
type Outcome = components["schemas"]["ResolveRequest"]["outcome"]

const OUTCOMES: { value: Outcome; label: string }[] = [
  { value: "counter", label: "Counter" },
  { value: "accept", label: "Accept" },
  { value: "decline", label: "Decline" },
]

export type ResolveDialogProps = {
  card: ThreadCard
  events: ThreadEventView[]
  transcripts: TranscriptViewModel[]
  open: boolean
  onClose: () => void
  onChanged: () => void
}

/** The newest thing the creator said: a reply they emailed, or a call. */
function newestWords(
  transcripts: TranscriptViewModel[]
): TranscriptViewModel | null {
  const said = transcripts.filter(
    (t) => t.kind === "email_in" || t.kind === "call"
  )
  return (
    said.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null
  )
}

/**
 * Settles a reply the system could not read with confidence: what the creator said sits
 * beside the terms it took from it, and the brand counters, accepts or declines. What is
 * sent is bound to the terms event the dialog opened on.
 */
export function ResolveDialog({
  card,
  events,
  transcripts,
  open,
  onClose,
  onChanged,
}: ResolveDialogProps) {
  const api = useApi()
  const [busy, setBusy] = React.useState(false)
  const [outcome, setOutcome] = React.useState<Outcome>("counter")
  const [draft, setDraft] = React.useState<TermsDraft>({ conditions: [] })

  // What is shown when the dialog opens is what is acted on: the terms read from the
  // reply, and the event they came from. A refetch while it is open changes neither.
  const [bound, setBound] = React.useState<{
    eventId: number | null
    summary: string
  } | null>(null)
  if (!open) {
    if (bound !== null) setBound(null)
  } else if (bound === null) {
    const event = events.find((e) => e.id === card.terms_event_id)
    const read = termsToDraft(event?.terms ?? card.latest_terms)
    setBound({ eventId: card.terms_event_id, summary: termsSummary(read) })
    setDraft(read)
    setOutcome("counter")
  }
  const eventId = bound ? bound.eventId : card.terms_event_id

  const words = React.useMemo(() => newestWords([...transcripts]), [transcripts])
  const input = draftToInput(draft)
  const canSend = outcome !== "counter" || input !== null

  async function resolve() {
    if (!canSend) return
    setBusy(true)
    try {
      const { error } = await api.POST("/api/v1/threads/{thread_id}/resolve", {
        params: { path: { thread_id: card.id } },
        body:
          outcome === "counter"
            ? { outcome, terms: input, based_on_event_id: eventId }
            : { outcome, based_on_event_id: eventId },
      })
      if (!error) {
        toast.success("Resolved")
        onClose()
        onChanged()
        return
      }
      if (reportActionError(error) === "refetch") {
        onClose()
        onChanged()
      }
    } catch {
      toast.error(GENERIC_ERROR)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Resolve {card.creator.name}&apos;s reply</DialogTitle>
          <DialogDescription>
            The reply was hard to read. Check what {card.creator.name} said
            against the terms taken from it, then decide.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 md:grid-cols-2">
          <section className="flex min-w-0 flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              What they said
            </h3>
            <div className="max-h-72 overflow-y-auto rounded-lg border p-3">
              {words ? (
                <TranscriptView transcript={words} />
              ) : (
                <p className="text-sm text-muted-foreground">
                  No reply on record.
                </p>
              )}
            </div>
          </section>

          <section className="flex min-w-0 flex-col gap-3">
            <fieldset className="m-0 flex flex-wrap gap-4 border-0 p-0">
              <legend className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Outcome
              </legend>
              {OUTCOMES.map((option) => (
                <label
                  key={option.value}
                  className="flex items-center gap-2 text-sm"
                >
                  <input
                    type="radio"
                    name={`resolve-outcome-${card.id}`}
                    value={option.value}
                    checked={outcome === option.value}
                    disabled={busy}
                    onChange={() => setOutcome(option.value)}
                    className="size-4 accent-foreground"
                  />
                  {option.label}
                </label>
              ))}
            </fieldset>

            {outcome === "counter" ? (
              <TermsCard value={draft} onChange={setDraft} disabled={busy} />
            ) : null}
            {outcome === "accept" ? (
              <p className="num rounded-lg border bg-muted/40 p-3 text-sm">
                {bound?.summary
                  ? `Accepts the terms read from the reply: ${bound.summary}`
                  : "Accepts the terms read from the reply."}
              </p>
            ) : null}
            {outcome === "decline" ? (
              <p className="rounded-lg border bg-muted/40 p-3 text-sm">
                Closes the conversation with {card.creator.name}.
              </p>
            ) : null}
          </section>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={busy || !canSend}
            onClick={() => void resolve()}
          >
            Resolve
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

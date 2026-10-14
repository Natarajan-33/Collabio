"use client"

import * as React from "react"
import { toast } from "sonner"

import { TermsCard } from "@/components/deal/terms-card"
import { PREVIEW_DEBOUNCE_MS } from "@/components/offers/offer-actions"
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
import { apiErrorCode, apiErrorDetail } from "@/lib/api/errors"
import type { components } from "@/lib/api/schema"
import { GENERIC_ERROR, reportActionError } from "@/lib/board/action-error"
import { draftToInput, type TermsDraft } from "@/lib/deal/terms"

type ThreadCard = components["schemas"]["ThreadCard"]

type Preview = {
  key: string
  ceiling: string | null
  headline: string | null
}

export type CounterDialogProps = {
  card: ThreadCard
  open: boolean
  onClose: () => void
  /** The counter being edited. The board owns it, so voice can fill it in. */
  draft: TermsDraft
  onDraftChange: (draft: TermsDraft) => void
  /** The thread moved on, or the terms it showed did: load it again. */
  onChanged: () => void
}

/**
 * The brand's counter to a creator's terms. It edits terms with a live preview against
 * the package and the brand's private ceiling, and sends them bound to the event it was
 * opened on: if the creator's terms move while it is open, the send is refused rather
 * than answering terms the brand never saw.
 */
export function CounterDialog({
  card,
  open,
  onClose,
  draft,
  onDraftChange,
  onChanged,
}: CounterDialogProps) {
  const api = useApi()
  const threadId = card.id
  const [busy, setBusy] = React.useState(false)

  // The terms the brand sees when the dialog opens are the ones it answers. A refetch
  // while it is open replaces `card`, but must not change the event the send is bound to.
  const [bound, setBound] = React.useState<{ eventId: number | null } | null>(
    null
  )
  if (!open) {
    if (bound !== null) setBound(null)
  } else if (bound === null) {
    setBound({ eventId: card.terms_event_id })
  }
  const eventId = bound ? bound.eventId : card.terms_event_id

  // Previews and server verdicts belong to the exact terms they were made for, so
  // editing invalidates them without any resetting.
  const inputKey = React.useMemo(() => {
    const input = draftToInput(draft)
    return input ? JSON.stringify(input) : null
  }, [draft])
  const [preview, setPreview] = React.useState<Preview | null>(null)
  const [serverCeiling, setServerCeiling] = React.useState<{
    key: string
    message: string
  } | null>(null)

  React.useEffect(() => {
    if (!open || !inputKey) return
    let gone = false
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.POST(
          "/api/v1/threads/{thread_id}/counter/preview",
          {
            params: { path: { thread_id: threadId } },
            body: { terms: JSON.parse(inputKey) },
          }
        )
        if (gone || !data) return
        setPreview({
          key: inputKey,
          ceiling: data.ceiling_violation,
          headline: data.delta.latest_headline ?? data.delta.headline,
        })
      } catch {
        // No preview: the server still checks the ceiling when it is sent.
      }
    }, PREVIEW_DEBOUNCE_MS)
    return () => {
      gone = true
      clearTimeout(timer)
    }
  }, [api, open, inputKey, threadId])

  const fresh = preview && preview.key === inputKey ? preview : null
  const ceilingMessage =
    fresh?.ceiling ??
    (serverCeiling && serverCeiling.key === inputKey
      ? serverCeiling.message
      : null)

  async function send() {
    const input = draftToInput(draft)
    if (!input || !inputKey || ceilingMessage) return
    setBusy(true)
    try {
      const { error } = await api.POST("/api/v1/threads/{thread_id}/counter", {
        params: { path: { thread_id: threadId } },
        body: {
          terms: input,
          note: draft.note?.trim() ? draft.note : null,
          based_on_event_id: eventId,
        },
      })
      if (!error) {
        toast.success("Counter sent")
        onClose()
        onChanged()
        return
      }
      if (apiErrorCode(error) === "above_ceiling") {
        setServerCeiling({
          key: inputKey,
          message: apiErrorDetail(error)?.message ?? GENERIC_ERROR,
        })
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
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Counter {card.creator.name}</DialogTitle>
          <DialogDescription>
            Set the terms you would take. {card.creator.name} sees them once you
            send.
          </DialogDescription>
        </DialogHeader>

        <TermsCard
          value={draft}
          onChange={onDraftChange}
          ceilingMessage={ceilingMessage}
          showNote
          disabled={busy}
        />

        {fresh?.headline ? (
          <p data-slot="counter-preview" className="text-sm">
            {fresh.headline}
          </p>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={busy || !inputKey || ceilingMessage !== null}
            onClick={() => void send()}
          >
            Send counter
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

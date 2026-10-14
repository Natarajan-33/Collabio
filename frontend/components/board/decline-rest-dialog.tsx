"use client"

import * as React from "react"
import { toast } from "sonner"

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
import { STATUS_LABEL } from "@/lib/board/state"

type DeclineRestPreview = components["schemas"]["DeclineRestPreview"]

export type DeclineRestDialogProps = {
  batchId: string
  open: boolean
  onClose: () => void
  /** The remaining conversations were closed: load the board again. */
  onDone: () => void
}

/**
 * Once the hires are made, politely closes every conversation still open. It lists who
 * would be closed first; nothing is sent until the brand confirms.
 */
export function DeclineRestDialog({
  batchId,
  open,
  onClose,
  onDone,
}: DeclineRestDialogProps) {
  const api = useApi()
  const [preview, setPreview] = React.useState<DeclineRestPreview | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [busy, setBusy] = React.useState(false)

  // Each opening starts from a fresh look at who is still open.
  if (!open && (preview !== null || failed)) {
    setPreview(null)
    setFailed(false)
  }

  React.useEffect(() => {
    if (!open) return
    let gone = false
    void (async () => {
      try {
        const { data } = await api.POST(
          "/api/v1/batches/{batch_id}/decline-rest/preview",
          { params: { path: { batch_id: batchId } } }
        )
        if (gone) return
        if (data) setPreview(data)
        else setFailed(true)
      } catch {
        if (!gone) setFailed(true)
      }
    })()
    return () => {
      gone = true
    }
  }, [api, batchId, open])

  const count = preview?.will_close.length ?? 0

  async function confirm() {
    setBusy(true)
    try {
      const { data, error } = await api.POST(
        "/api/v1/batches/{batch_id}/decline-rest",
        { params: { path: { batch_id: batchId } } }
      )
      if (error || !data) {
        reportActionError(error)
        return
      }
      toast.success(
        `Declined ${data.closed.length} ${data.closed.length === 1 ? "creator" : "creators"}`
      )
      if (data.failed.length > 0) {
        toast.error(`${data.failed.length} could not be declined`)
      }
      onClose()
      onDone()
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
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Decline the remaining creators?</DialogTitle>
          <DialogDescription>
            Each one is told politely that you have hired. This cannot be
            undone.
          </DialogDescription>
        </DialogHeader>

        {failed ? (
          <p className="text-sm text-destructive">
            Could not check who is still open. Try again.
          </p>
        ) : preview === null ? (
          <p className="text-sm text-muted-foreground">Checking…</p>
        ) : count === 0 ? (
          <p className="text-sm text-muted-foreground">
            No open conversations to decline.
          </p>
        ) : (
          <ul className="flex max-h-60 flex-col gap-1 overflow-y-auto text-sm">
            {preview.will_close.map((item) => (
              <li
                key={item.thread_id}
                className="flex items-baseline justify-between gap-3"
              >
                <span className="font-medium">{item.creator.name}</span>
                <span className="text-xs text-muted-foreground">
                  {STATUS_LABEL[item.status]}
                </span>
              </li>
            ))}
          </ul>
        )}

        {preview && preview.skipped.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Left alone: {preview.skipped.map((s) => s.creator.name).join(", ")}
          </p>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          {count > 0 ? (
            <Button
              type="button"
              variant="destructive"
              disabled={busy}
              onClick={() => void confirm()}
            >
              Decline {count} {count === 1 ? "creator" : "creators"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

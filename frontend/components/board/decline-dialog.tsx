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
import { Label } from "@/components/ui/label"
import { useApi } from "@/hooks/use-api"
import type { components } from "@/lib/api/schema"
import { GENERIC_ERROR, reportActionError } from "@/lib/board/action-error"

type ThreadCard = components["schemas"]["ThreadCard"]

export type DeclineDialogProps = {
  card: ThreadCard
  /** Decline answers the creator's terms; withdraw takes back an offer they have not answered. */
  action: "decline" | "withdraw"
  open: boolean
  onClose: () => void
  onChanged: () => void
}

/** Ends a conversation, with an optional reason. Nothing is sent until it is confirmed. */
export function DeclineDialog({
  card,
  action,
  open,
  onClose,
  onChanged,
}: DeclineDialogProps) {
  const api = useApi()
  const [reason, setReason] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const reasonId = React.useId()
  const name = card.creator.name

  // A fresh dialog starts with no reason.
  const [wasOpen, setWasOpen] = React.useState(open)
  if (wasOpen !== open) {
    setWasOpen(open)
    if (open) setReason("")
  }

  async function confirm() {
    const text = reason.trim()
    setBusy(true)
    try {
      const { error } = await api.POST("/api/v1/threads/{thread_id}/decline", {
        params: { path: { thread_id: card.id } },
        body: { reason: text === "" ? null : text },
      })
      if (!error) {
        toast.success(
          action === "withdraw" ? "Offer withdrawn" : "Creator declined"
        )
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
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {action === "withdraw"
              ? `Withdraw your offer to ${name}?`
              : `Decline ${name}?`}
          </DialogTitle>
          <DialogDescription>
            This closes the conversation with {name}.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor={reasonId}>Reason (optional)</Label>
          <textarea
            id={reasonId}
            value={reason}
            rows={3}
            maxLength={1000}
            onChange={(event) => setReason(event.target.value)}
            className="w-full min-w-0 resize-y rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={busy}
            onClick={() => void confirm()}
          >
            {action === "withdraw" ? "Withdraw offer" : "Decline creator"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

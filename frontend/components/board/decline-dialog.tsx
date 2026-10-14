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

type ThreadCard = components["schemas"]["ThreadCard"]

export type DeclineDialogProps = {
  card: ThreadCard
  /** Decline answers the creator's terms; withdraw takes back an offer they have not answered. */
  action: "decline" | "withdraw"
  open: boolean
  onClose: () => void
  onChanged: () => void
}

/**
 * Ends a conversation. Nothing is sent until it is confirmed. There is no reason to
 * give: what a brand types is never stored or passed on to the creator.
 */
export function DeclineDialog({
  card,
  action,
  open,
  onClose,
  onChanged,
}: DeclineDialogProps) {
  const api = useApi()
  const [busy, setBusy] = React.useState(false)
  const name = card.creator.name

  async function confirm() {
    setBusy(true)
    try {
      const { error } = await api.POST("/api/v1/threads/{thread_id}/decline", {
        params: { path: { thread_id: card.id } },
        body: {},
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

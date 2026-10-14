"use client"

import * as React from "react"
import { toast } from "sonner"

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
import { Label } from "@/components/ui/label"
import { useApi } from "@/hooks/use-api"
import { apiErrorCode, apiErrorDetail } from "@/lib/api/errors"
import { PREVIEW_DEBOUNCE_MS } from "@/lib/deal/constants"
import { brandOffer, type OfferDesk } from "@/lib/deal/offers"
import { draftToInput, termsSummary, type TermsDraft } from "@/lib/deal/terms"
import { formatCents } from "@/lib/money"

export type OfferDialog = "accept" | "decline" | "counter"

const TERMS_CHANGED_MESSAGE = "Terms changed — review the latest"
const GENERIC_ERROR = "Something went wrong. Try again."

export type OfferActionsProps = {
  desk: OfferDesk
  /** Which dialog is open; the page owns it so voice can open one. */
  dialog: OfferDialog | null
  onOpenDialog: (dialog: OfferDialog) => void
  onCloseDialog: () => void
  /** The counter being edited. */
  draft: TermsDraft
  onDraftChange: (draft: TermsDraft) => void
  /** The decline reason being typed. */
  reason: string
  onReasonChange: (reason: string) => void
  /**
   * The offer moved on. `desk` is the new state when the API sent it, else null and the
   * page loads it again. `termsChanged` means the other side's terms moved under the
   * creator's feet: the page flags what changed.
   */
  onChanged: (change: { desk: OfferDesk | null; termsChanged: boolean }) => void
}

type Preview = { key: string; floor: number | null; headline: string | null }

/**
 * What the creator can do about an offer: only the actions the API allows. Each opens a
 * dialog that shows what is about to happen and sends nothing until it is confirmed.
 * Accepting names the exact terms; declining takes an optional reason; countering edits
 * terms with a live preview against the creator's private floor, and sending below it
 * needs a second, separate confirmation.
 */
export function OfferActions({
  desk,
  dialog,
  onOpenDialog,
  onCloseDialog,
  draft,
  onDraftChange,
  reason,
  onReasonChange,
  onChanged,
}: OfferActionsProps) {
  const api = useApi()
  const threadId = desk.thread_id
  const allowed = new Set(desk.allowed_actions)
  const [busy, setBusy] = React.useState(false)

  // What the creator is shown when a dialog opens is what they act on. A refetch while
  // it is open (the doorbell) replaces `desk`, but must not change the terms, or the
  // event they are bound to, under a confirmation they have already read.
  const [snapshot, setSnapshot] = React.useState<{
    dialog: OfferDialog
    eventId: number | null
    offer: OfferDesk["my_package"]
  } | null>(null)
  if (dialog === null) {
    if (snapshot !== null) setSnapshot(null)
  } else if (snapshot?.dialog !== dialog) {
    setSnapshot({
      dialog,
      eventId: desk.terms_event_id,
      offer: brandOffer(desk),
    })
  }
  const eventId = snapshot ? snapshot.eventId : desk.terms_event_id

  // Counter-only state. Previews, the floor confirmation and a floor the server found
  // are all tied to the exact terms they were made for, so editing invalidates them
  // without any resetting.
  const inputKey = React.useMemo(() => {
    const input = draftToInput(draft)
    return input ? JSON.stringify(input) : null
  }, [draft])
  const [preview, setPreview] = React.useState<Preview | null>(null)
  const [serverFloor, setServerFloor] = React.useState<{
    key: string
    cents: number
  } | null>(null)
  const [confirmKey, setConfirmKey] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (dialog !== "counter" || !inputKey) return
    let gone = false
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.POST(
          "/api/v1/offers/{thread_id}/counter/preview",
          {
            params: { path: { thread_id: threadId } },
            body: { terms: JSON.parse(inputKey) },
          }
        )
        if (gone || !data) return
        setPreview({
          key: inputKey,
          floor: data.below_floor_by_cents,
          headline: data.delta.latest_headline ?? data.delta.headline,
        })
      } catch {
        // No preview: the creator can still send, and the server checks the floor.
      }
    }, PREVIEW_DEBOUNCE_MS)
    return () => {
      gone = true
      clearTimeout(timer)
    }
  }, [api, dialog, inputKey, threadId])

  const freshPreview = preview && preview.key === inputKey ? preview : null
  const floorCents =
    freshPreview?.floor ??
    (serverFloor && serverFloor.key === inputKey ? serverFloor.cents : null)
  const belowFloor = floorCents != null && floorCents > 0
  const confirmingFloor = belowFloor && confirmKey === inputKey

  function close() {
    setConfirmKey(null)
    onCloseDialog()
  }

  /** Runs a request; the outcome is a new desk, a conflict, or a message. */
  async function run<T extends { data?: OfferDesk; error?: unknown }>(
    request: () => Promise<T>,
    success: string
  ): Promise<unknown> {
    setBusy(true)
    try {
      const result = await request()
      if (result.error === undefined || result.error === null) {
        toast.success(success)
        close()
        onChanged({ desk: result.data ?? null, termsChanged: false })
        return undefined
      }
      const code = apiErrorCode(result.error)
      if (code === "terms_changed") {
        toast.info(TERMS_CHANGED_MESSAGE)
        close()
        onChanged({ desk: null, termsChanged: true })
      } else if (code === "action_not_allowed" || code === "stale_status") {
        toast.error(apiErrorDetail(result.error)?.message ?? GENERIC_ERROR)
        close()
        onChanged({ desk: null, termsChanged: false })
      } else if (code !== "below_floor") {
        toast.error(apiErrorDetail(result.error)?.message ?? GENERIC_ERROR)
      }
      return result.error
    } catch {
      toast.error(GENERIC_ERROR)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function accept() {
    await run(
      () =>
        api.POST("/api/v1/offers/{thread_id}/accept", {
          params: { path: { thread_id: threadId } },
          body: { based_on_event_id: eventId },
        }),
      "Offer accepted"
    )
  }

  async function decline() {
    const text = reason.trim()
    await run(
      () =>
        api.POST("/api/v1/offers/{thread_id}/decline", {
          params: { path: { thread_id: threadId } },
          body: { reason: text === "" ? null : text },
        }),
      "Offer declined"
    )
  }

  async function sendCounter() {
    const input = draftToInput(draft)
    if (!input || !inputKey) return
    if (belowFloor && !confirmingFloor) {
      setConfirmKey(inputKey)
      return
    }
    const error = await run(
      () =>
        api.POST("/api/v1/offers/{thread_id}/counter", {
          params: { path: { thread_id: threadId } },
          body: {
            terms: input,
            based_on_event_id: eventId,
            confirm_below_floor: confirmingFloor,
            note: draft.note?.trim() ? draft.note : null,
          },
        }),
      "Counter sent"
    )
    if (apiErrorCode(error) === "below_floor") {
      // The preview did not catch it (or the floor moved): ask before sending.
      const cents = apiErrorDetail<{ below_by_cents?: number }>(
        error
      )?.below_by_cents
      if (cents && cents > 0) {
        setServerFloor({ key: inputKey, cents })
        setConfirmKey(inputKey)
      }
    }
  }

  const offer = snapshot?.offer ?? brandOffer(desk)
  const extras = [...offer.conditions]

  return (
    <>
      <div
        data-slot="offer-actions"
        className="flex flex-wrap items-center gap-2"
      >
        {allowed.has("accept") ? (
          <Button type="button" onClick={() => onOpenDialog("accept")}>
            Accept
          </Button>
        ) : null}
        {allowed.has("counter") ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenDialog("counter")}
          >
            Counter
          </Button>
        ) : null}
        {allowed.has("decline") ? (
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenDialog("decline")}
          >
            Decline
          </Button>
        ) : null}
      </div>

      <Dialog
        open={dialog === "accept"}
        onOpenChange={(open) => {
          if (!open) close()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Accept this offer?</DialogTitle>
            <DialogDescription>
              {desk.brand.name} gets your yes on exactly these terms.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2 rounded-lg border bg-muted/40 p-3">
            <p className="num font-medium">{termsSummary(offer)}</p>
            {extras.length > 0 ? (
              <ul className="flex flex-wrap gap-2 text-sm">
                {extras.map((text, index) => (
                  <li
                    key={`${text}-${index}`}
                    className="rounded-full border bg-background px-3 py-0.5"
                  >
                    {text}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button type="button" disabled={busy} onClick={() => void accept()}>
              Accept these terms
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={dialog === "decline"}
        onOpenChange={(open) => {
          if (!open) close()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Decline this offer?</DialogTitle>
            <DialogDescription>
              This ends the conversation with {desk.brand.name}.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="decline-reason">Reason (optional)</Label>
            <textarea
              id="decline-reason"
              value={reason}
              rows={3}
              maxLength={1000}
              onChange={(event) => onReasonChange(event.target.value)}
              className="w-full min-w-0 resize-y rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={busy}
              onClick={() => void decline()}
            >
              Decline offer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={dialog === "counter"}
        onOpenChange={(open) => {
          if (!open) close()
        }}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Counter this offer</DialogTitle>
            <DialogDescription>
              Set the terms you would take. {desk.brand.name} sees them once you
              send.
            </DialogDescription>
          </DialogHeader>

          <TermsCard
            value={draft}
            onChange={onDraftChange}
            floorWarningCents={belowFloor ? floorCents : null}
            showNote
            disabled={busy}
          />

          {freshPreview?.headline ? (
            <p data-slot="counter-preview" className="text-sm">
              {freshPreview.headline}
            </p>
          ) : null}

          {confirmingFloor && floorCents != null ? (
            <p
              role="alert"
              className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              This is <span className="num">{formatCents(floorCents)}</span>{" "}
              below your floor. Send it only if you mean to.
            </p>
          ) : null}

          <DialogFooter>
            {confirmingFloor ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setConfirmKey(null)}
                >
                  Back
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  disabled={busy || !inputKey}
                  onClick={() => void sendCounter()}
                >
                  Send below my floor
                </Button>
              </>
            ) : (
              <>
                <Button type="button" variant="outline" onClick={close}>
                  Cancel
                </Button>
                <Button
                  type="button"
                  disabled={busy || !inputKey}
                  onClick={() => void sendCounter()}
                >
                  Send counter
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

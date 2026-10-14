"use client"

import * as React from "react"
import { toast } from "sonner"

import { MilestoneEditor } from "@/components/deal/milestone-editor"
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
import {
  GENERIC_ERROR,
  TERMS_CHANGED_MESSAGE,
} from "@/lib/board/action-error"
import { milestoneErrors, type MilestoneDraft } from "@/lib/deal/milestones"
import { termsSummary } from "@/lib/deal/terms"
import { formatCents } from "@/lib/money"

type AwardPreview = components["schemas"]["AwardPreview"]
type DealView = components["schemas"]["DealView"]

export type AwardDialogProps = {
  threadId: string
  /** Who is being awarded, for the title. */
  creatorName?: string
  open: boolean
  onOpenChange: (open: boolean) => void
  /** The deal is booked. */
  onAwarded: (deal: DealView) => void
  /** The thread can no longer be awarded: the board should load it again. */
  onStale?: () => void
}

function Confirmation({
  checked,
  onChange,
  disabled,
  children,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled: boolean
  children: React.ReactNode
}) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 accent-foreground"
      />
      <span>{children}</span>
    </label>
  )
}

/**
 * Books a deal. It previews the agreed terms and a payment schedule, one payment per
 * video, to edit; asks for a separate yes to anything that breaks the brand's own
 * limits (its ceiling, its hiring target); and, once the target is reached, offers to
 * politely decline everyone else still open. What is sent is bound to the terms that
 * were previewed, so terms that moved meanwhile are re-previewed, never booked unseen.
 */
export function AwardDialog({
  threadId,
  creatorName,
  open,
  onOpenChange,
  onAwarded,
  onStale,
}: AwardDialogProps) {
  const api = useApi()
  const [preview, setPreview] = React.useState<AwardPreview | null>(null)
  const [milestones, setMilestones] = React.useState<MilestoneDraft[]>([])
  const [loadFailed, setLoadFailed] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [overCeiling, setOverCeiling] = React.useState(false)
  const [overTarget, setOverTarget] = React.useState(false)
  const [declineRest, setDeclineRest] = React.useState(true)
  // What the server found wrong with the schedule it was sent: tied to that schedule,
  // so editing it clears the message.
  const [serverIssue, setServerIssue] = React.useState<{
    key: string
    errors: string[]
  } | null>(null)
  // Bumped to load the preview again.
  const [load, setLoad] = React.useState(0)

  // Each opening starts from a fresh preview.
  if (!open && (preview !== null || loadFailed)) {
    setPreview(null)
    setMilestones([])
    setLoadFailed(false)
    setServerIssue(null)
  }

  React.useEffect(() => {
    if (!open) return
    let gone = false
    void (async () => {
      try {
        const { data } = await api.POST(
          "/api/v1/threads/{thread_id}/award/preview",
          { params: { path: { thread_id: threadId } } }
        )
        if (gone) return
        if (!data) {
          setLoadFailed(true)
          return
        }
        setPreview(data)
        setMilestones(data.milestones)
        setLoadFailed(false)
        setServerIssue(null)
        // Confirmations were for the terms that were previewed before.
        setOverCeiling(false)
        setOverTarget(false)
        setDeclineRest(true)
      } catch {
        if (!gone) setLoadFailed(true)
      }
    })()
    return () => {
      gone = true
    }
  }, [api, open, threadId, load])

  const scheduleKey = JSON.stringify(milestones)
  const problems = preview ? milestoneErrors(preview.agreed, milestones) : []
  const needsCeiling =
    preview?.over_ceiling_cents != null && preview.over_ceiling_cents > 0
  const needsTarget = preview?.over_target === true
  const offerDeclineRest =
    preview !== null &&
    preview.would_reach_target &&
    preview.open_others.length > 0

  const canConfirm =
    preview !== null &&
    !busy &&
    problems.length === 0 &&
    (!needsCeiling || overCeiling) &&
    (!needsTarget || overTarget)

  async function confirm() {
    if (!preview || !canConfirm) return
    setBusy(true)
    try {
      const { data: deal, error } = await api.POST(
        "/api/v1/threads/{thread_id}/award",
        {
          params: { path: { thread_id: threadId } },
          body: {
            milestones,
            based_on_event_id: preview.terms_event_id,
            confirm_over_ceiling: needsCeiling && overCeiling,
            confirm_over_target: needsTarget && overTarget,
          },
        }
      )
      if (error || !deal) {
        const code = apiErrorCode(error)
        if (code === "milestones_invalid") {
          const issues = apiErrorDetail<{ errors?: string[] }>(error)?.errors
          setServerIssue({
            key: scheduleKey,
            errors: issues?.length ? issues : ["The payment schedule is not valid"],
          })
        } else if (code === "terms_changed") {
          toast.info(TERMS_CHANGED_MESSAGE)
          setLoad((n) => n + 1)
        } else if (code === "over_ceiling" || code === "over_target") {
          // Where the brand stands moved since the preview: show it again.
          toast.error(apiErrorDetail(error)?.message ?? GENERIC_ERROR)
          setLoad((n) => n + 1)
        } else if (code === "action_not_allowed" || code === "stale_status") {
          toast.error(apiErrorDetail(error)?.message ?? GENERIC_ERROR)
          onOpenChange(false)
          onStale?.()
        } else {
          toast.error(apiErrorDetail(error)?.message ?? GENERIC_ERROR)
        }
        return
      }

      if (offerDeclineRest && declineRest) {
        try {
          const rest = await api.POST(
            "/api/v1/batches/{batch_id}/decline-rest",
            { params: { path: { batch_id: deal.batch_id } } }
          )
          if (rest.error || !rest.data || rest.data.failed.length > 0) {
            toast.error("The deal is booked, but not everyone could be declined")
          }
        } catch {
          toast.error("The deal is booked, but not everyone could be declined")
        }
      }
      toast.success("Deal booked")
      onOpenChange(false)
      onAwarded(deal)
    } catch {
      toast.error(GENERIC_ERROR)
    } finally {
      setBusy(false)
    }
  }

  const shownIssues =
    serverIssue && serverIssue.key === scheduleKey ? serverIssue.errors : []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {creatorName ? `Award ${creatorName}` : "Award this creator"}
          </DialogTitle>
          <DialogDescription>
            Booking fixes the terms below and the payment for each video.
          </DialogDescription>
        </DialogHeader>

        {loadFailed ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-destructive">
              Could not load the terms to award.
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setLoadFailed(false)
                setLoad((n) => n + 1)
              }}
            >
              Try again
            </Button>
          </div>
        ) : preview === null ? (
          <p className="text-sm text-muted-foreground">Checking the terms…</p>
        ) : (
          <>
            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Agreed terms
              </h3>
              <p className="num font-medium">{termsSummary(preview.agreed)}</p>
              {preview.agreed.conditions.length > 0 ||
              preview.agreed.addons.length > 0 ? (
                <ul className="flex flex-wrap gap-2">
                  {[...preview.agreed.conditions, ...preview.agreed.addons].map(
                    (text, index) => (
                      <li
                        key={`${text}-${index}`}
                        className="inline-flex h-7 items-center rounded-full border bg-muted/50 px-3 text-sm"
                      >
                        {text}
                      </li>
                    )
                  )}
                </ul>
              ) : null}
            </section>

            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Payment schedule
              </h3>
              <MilestoneEditor
                agreed={preview.agreed}
                value={milestones}
                onChange={setMilestones}
                disabled={busy}
              />
              {shownIssues.length > 0 ? (
                <ul
                  role="alert"
                  className="flex flex-col gap-0.5 text-sm text-destructive"
                >
                  {shownIssues.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              ) : null}
            </section>

            {needsCeiling || needsTarget || offerDeclineRest ? (
              <section className="flex flex-col gap-3 rounded-lg border bg-muted/30 p-3">
                {needsCeiling ? (
                  <Confirmation
                    checked={overCeiling}
                    onChange={setOverCeiling}
                    disabled={busy}
                  >
                    Award{" "}
                    <span className="num">
                      {formatCents(preview.over_ceiling_cents ?? 0)}
                    </span>{" "}
                    over my ceiling
                  </Confirmation>
                ) : null}
                {needsTarget ? (
                  <Confirmation
                    checked={overTarget}
                    onChange={setOverTarget}
                    disabled={busy}
                  >
                    Hire beyond my target of{" "}
                    <span className="num">{preview.hires_target}</span>
                  </Confirmation>
                ) : null}
                {offerDeclineRest ? (
                  <div className="flex flex-col gap-1">
                    <Confirmation
                      checked={declineRest}
                      onChange={setDeclineRest}
                      disabled={busy}
                    >
                      Politely decline the remaining{" "}
                      <span className="num">{preview.open_others.length}</span>
                    </Confirmation>
                    <p className="pl-6 text-xs text-muted-foreground">
                      {preview.open_others.map((c) => c.name).join(", ")}
                    </p>
                  </div>
                ) : null}
              </section>
            ) : null}
          </>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!canConfirm}
            onClick={() => void confirm()}
          >
            Confirm award
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
